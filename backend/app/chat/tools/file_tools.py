"""File operation tools for reading uploaded files."""

import asyncio
import copy
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...config.database import SessionLocal
from ...config.settings import settings
from ...logging import log_event
from ...utils.coerce import coerce_int
from ...services.files import (
    blob_storage_service as default_blob_storage_service,
    search_project_chunks_hybrid as default_project_search_service,
)

logger = logging.getLogger(__name__)


_IMAGE_TYPES = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
}
_IMAGE_EXTENSION_TO_MEDIA_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}
_MAX_IMAGE_DIMENSION = 2000
_EMPTY_QUERY_TOKENS = frozenset({"", "*", "all"})


def _invoke_project_search_service(
    project_search_service: Callable[..., Dict[str, Any]],
    *,
    query: str,
    project_id: str,
    db: Any,
    limit: int,
    user_id: Optional[str],
    conversation_id: Optional[str],
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "query": query,
        "project_id": project_id,
        "db": db,
        "limit": limit,
        "user_id": user_id,
        "conversation_id": conversation_id,
    }

    try:
        signature = inspect.signature(project_search_service)
    except (TypeError, ValueError):
        return project_search_service(**kwargs)

    parameters = signature.parameters
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return project_search_service(**kwargs)

    filtered_kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    return project_search_service(**filtered_kwargs)


def _execute_search_project_files_sync(
    *,
    query: str,
    project_id: str,
    db: Any,
    project_search_service: Callable[..., Dict[str, Any]],
    search_limit: int,
    user_id: Optional[str],
    conversation_id: Optional[str],
) -> Dict[str, Any]:
    def _build_search_response(*, status: str, query_value: str, message: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        log_event(
            logger,
            "INFO",
            "tool.retrieval_project_files.completed",
            "tool",
            user_id=user_id,
            conversation_id=conversation_id,
            project_id=project_id,
            status=status,
            query_char_count=len(query_value),
            result_count=len(results),
            limit=search_limit,
        )
        return {
            "query": query_value,
            "message": message,
            "results": results,
        }

    if query in _EMPTY_QUERY_TOKENS:
        from ...database.models import File  # local import to avoid cycles

        rows = (
            db.query(File)
            .filter(File.project_id == project_id, File.parent_file_id.is_(None))
            .order_by(File.created_at.desc())
            .limit(search_limit)
            .all()
        )

        results = [
            {
                "file_id": f.id,
                "filename": f.original_filename,
                "file_type": f.file_type,
                "file_size": f.file_size,
                "excerpts": [],
                "match_count": 0,
                "filename_match": False,
            }
            for f in rows
        ]

        return _build_search_response(
            status="latest_files",
            query_value="latest files",
            message=f"Latest {len(results)} project file(s)",
            results=results,
        )

    search_payload = _invoke_project_search_service(
        project_search_service,
        query=query,
        project_id=project_id,
        db=db,
        limit=search_limit,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    status = str(search_payload.get("status") or "no_match")
    results = list(search_payload.get("results") or [])

    if status == "not_ready":
        pending_file_count = int(search_payload.get("pending_file_count") or 0)
        total_file_count = int(search_payload.get("total_file_count") or 0)
        indexed_file_count = int(search_payload.get("indexed_file_count") or 0)
        return _build_search_response(
            status="not_ready",
            query_value=query,
            message=(
                "Project files are still being indexed. "
                f"{indexed_file_count}/{total_file_count} file(s) indexed, "
                f"{pending_file_count} pending."
            ),
            results=[],
        )

    if status == "no_files":
        return _build_search_response(
            status="no_files",
            query_value=query,
            message="No project knowledge files are available yet.",
            results=[],
        )

    if status == "failed":
        failed_file_count = int(search_payload.get("failed_file_count") or 0)
        return _build_search_response(
            status="failed",
            query_value=query,
            message=(
                "Project file indexing failed before any files were indexed. "
                f"{failed_file_count} file(s) failed. Re-upload failed files and retry."
            ),
            results=[],
        )

    if not results:
        return _build_search_response(
            status="no_match",
            query_value=query,
            message=f"No indexed project files found matching '{query}'",
            results=[],
        )

    return _build_search_response(
        status="ok",
        query_value=query,
        message=f"Found {len(results)} file(s) matching '{query}'",
        results=results,
    )


def _resolve_image_media_type(file_type: str) -> str:
    normalized = (file_type or "").lower()
    if normalized in _IMAGE_EXTENSION_TO_MEDIA_TYPE:
        return _IMAGE_EXTENSION_TO_MEDIA_TYPE[normalized]
    if normalized.startswith("image/"):
        return normalized
    return "image/jpeg"


def _encode_image_for_tool_content(
    *,
    blob_data: bytes,
    file_type: str,
    resize_event: str,
    resize_log_fields: Dict[str, Any],
) -> Tuple[str, str]:
    """Convert image bytes into a normalized base64 payload for chat tool input."""
    from io import BytesIO
    import base64

    from PIL import Image

    image = Image.open(BytesIO(blob_data))

    if image.width > _MAX_IMAGE_DIMENSION or image.height > _MAX_IMAGE_DIMENSION:
        if image.width > image.height:
            new_width = _MAX_IMAGE_DIMENSION
            new_height = int(image.height * (_MAX_IMAGE_DIMENSION / image.width))
        else:
            new_height = _MAX_IMAGE_DIMENSION
            new_width = int(image.width * (_MAX_IMAGE_DIMENSION / image.height))

        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        log_event(
            logger,
            "INFO",
            resize_event,
            "tool",
            width=new_width,
            height=new_height,
            **resize_log_fields,
        )

    if image.mode not in ("RGB", "L"):
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3] if len(image.split()) == 4 else None)
            image = background
        else:
            image = image.convert("RGB")

    preferred_media_type = _resolve_image_media_type(file_type)
    if preferred_media_type == "image/png":
        media_type = "image/png"
        output_format = "PNG"
    else:
        # Normalize everything else (jpg/jpeg/gif/webp/unknown) to JPEG for tool payload size.
        media_type = "image/jpeg"
        output_format = "JPEG"

    output_buffer = BytesIO()
    if output_format == "JPEG":
        image.save(output_buffer, format=output_format, quality=85)
    else:
        image.save(output_buffer, format=output_format)

    image_base64 = base64.b64encode(output_buffer.getvalue()).decode("utf-8")
    return image_base64, media_type


async def execute_search_project_files(
    arguments: Dict[str, Any],
    context: Dict[str, Any],
    yield_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute retrieval_project_files tool.

    Behavior:
    - If `query` is provided (non-empty), perform text/filename search.
    - If `query` is empty, missing, or equals '*' (or 'all'), return latest N top-level files.
    """
    query_raw = arguments.get("query")
    query = query_raw.strip() if isinstance(query_raw, str) else ""

    project_id = context.get("project_id")
    if not project_id:
        raise ValueError(
            "Project file search is only available within project conversations. "
            "This tool cannot be used in personal conversations."
        )

    project_search_service = (
        context.get("project_search_service")
        or context.get("search_project_chunks_hybrid")
        or default_project_search_service
    )
    if not project_search_service:
        raise RuntimeError("search_project_files is not configured")

    search_limit = max(1, min(coerce_int(arguments.get("limit", 10)) or 10, 25))
    user_id = str(context.get("user_id") or "") or None
    conversation_id = str(context.get("conversation_id") or "") or None
    if yield_fn:
        yield_fn(
            {
                "type": "tool_query",
                "name": "retrieval_project_files",
                "content": "latest files" if query in _EMPTY_QUERY_TOKENS else query,
            }
        )
    # Default hybrid project search does sync DB + embedding work.
    # Keep async stream responsiveness by isolating it in a worker thread
    # with an owned DB session.
    if project_search_service is default_project_search_service:
        def _run_with_scoped_session() -> Dict[str, Any]:
            scoped_db = SessionLocal()
            try:
                return _execute_search_project_files_sync(
                    query=query,
                    project_id=project_id,
                    db=scoped_db,
                    project_search_service=project_search_service,
                    search_limit=search_limit,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            finally:
                scoped_db.close()

        return await asyncio.to_thread(_run_with_scoped_session)

    db = context.get("db")
    if not db:
        raise RuntimeError("search_project_files is not configured")
    return _execute_search_project_files_sync(
        query=query,
        project_id=project_id,
        db=db,
        project_search_service=project_search_service,
        search_limit=search_limit,
        user_id=user_id,
        conversation_id=conversation_id,
    )


async def execute_read_uploaded_file(
    arguments: Dict[str, Any],
    context: Dict[str, Any],
    yield_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute file_read tool.

    For text files: returns parsed content in chunks
    For images: returns image content blocks for visual viewing
    """
    file_id = arguments.get("file_id")
    if not isinstance(file_id, str) or not file_id.strip():
        raise ValueError(
            "Missing 'file_id' parameter. Provide the UUID of the file to read "
            "(e.g., from retrieval_project_files search results)."
        )
    file_id = file_id.strip()

    allowed = context.get("allowed_file_ids")
    allowed_set = set(allowed or [])
    candidate = None
    if allowed_set and file_id not in allowed_set:
        # Gracefully re-verify permissions in case the list is stale
        file_service = context.get("file_service")
        db = context.get("db")
        user_id = context.get("user_id")
        conversation_id = context.get("conversation_id")
        project_id = context.get("project_id")
        if file_service and db and user_id:
            try:
                candidate = file_service.get_file_by_id(file_id, user_id, db)
            except Exception:
                candidate = None
        if not candidate:
            raise PermissionError(
                f"File '{file_id}' not found or you don't have access. "
                "Verify the file_id is correct and belongs to this conversation/project."
            )

        belongs_to_conversation = (
            conversation_id is not None and candidate.conversation_id == conversation_id
        )
        belongs_to_project = (
            project_id is not None and candidate.project_id == project_id
        )
        if not (belongs_to_conversation or belongs_to_project):
            raise PermissionError(
                f"File '{file_id}' exists but is not accessible in this conversation. "
                "Files are scoped to their conversation/project and cannot be accessed elsewhere."
            )

        # Update allowed list for subsequent tool calls in this stream
        allowed_set.add(file_id)
        if isinstance(allowed, list):
            allowed.append(file_id)
        context["allowed_file_ids"] = list(allowed_set)

    file_service = context.get("file_service")
    blob_storage_service = context.get("blob_storage_service") or default_blob_storage_service
    db = context.get("db")
    user_id = context.get("user_id")
    if not file_service or not blob_storage_service or not db or not user_id:
        raise RuntimeError("File reader is not configured")

    # Check if this is an image file - if so, return image content blocks
    # Get file metadata to check type
    file_record = candidate or file_service.get_file_by_id(file_id, user_id, db)
    if not file_record:
        raise ValueError(f"File '{file_id}' not found")

    file_type = (file_record.file_type or "").lower()
    is_image = file_type in _IMAGE_TYPES

    if is_image:
        # Download, resize if needed, and return as base64 for stable tool payload size
        if yield_fn:
            yield_fn({"type": "tool_query", "name": "file_read", "content": f"Reading image: {file_record.original_filename}"})

        try:
            # Download image from blob storage
            blob_data = blob_storage_service.get_bytes(file_record.filename)
            if not blob_data:
                raise ValueError("Failed to download image from storage")

            image_base64, media_type = _encode_image_for_tool_content(
                blob_data=blob_data,
                file_type=file_type,
                resize_event="tool.file_read.image_resized",
                resize_log_fields={
                    "file_id": file_id,
                    "filename": file_record.original_filename,
                },
            )

            return {
                "_content_blocks": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"Image: {file_record.original_filename} ({file_type}, {file_record.file_size} bytes)",
                    },
                ],
                "file_id": file_id,
                "filename": file_record.filename,
                "original_filename": file_record.original_filename,
                "file_type": file_record.file_type,
                "has_embedded_images": False,
            }
        except Exception as exc:
            log_event(
                logger,
                "ERROR",
                "tool.file_read.image_process_failed",
                "error",
                file_id=file_id,
                filename=file_record.original_filename,
                exc_info=exc,
            )
            raise ValueError(f"Failed to process image: {str(exc)}")

    # For spreadsheet files, return summary + guidance to use execute_code
    from ...config.file_types import SPREADSHEET_EXTENSIONS
    if file_type in SPREADSHEET_EXTENSIONS and not file_record.project_id:
        if yield_fn:
            yield_fn({"type": "tool_query", "name": "file_read", "content": f"Preview: {file_record.original_filename}"})

        content = file_record.extracted_text or ""
        if not content:
            content = f"(No preview available for {file_record.original_filename})"

        return {
            "file_id": file_record.id,
            "filename": file_record.filename,
            "original_filename": file_record.original_filename,
            "file_type": file_type,
            "content": content,
            "note": (
                "This is a metadata preview only. For full data analysis, filtering, "
                "charting, or generating output files, use the `execute_code` tool with "
                f'file_ids=["{file_record.id}"]. The file will be available in INPUT_DIR.'
            ),
        }

    # For non-images (documents), read text content and automatically include embedded images
    max_length = context.get("max_chunk_length") or settings.file_chunk_max_length or 50000

    def _normalize_range(start_val: Optional[Any], length_val: Optional[Any]) -> Tuple[int, int]:
        start_int = _ensure_int(start_val or 0, "start must be an integer >= 0")
        if start_int < 0:
            raise ValueError("start must be >= 0")

        if length_val is not None:
            length_int = _ensure_int(length_val, "length must be a positive integer")
        else:
            length_int = max_length

        if length_int <= 0:
            length_int = max_length
        if max_length and length_int > max_length:
            length_int = max_length

        return start_int, length_int

    full_arg = arguments.get("full")
    if full_arg is not None and not isinstance(full_arg, bool):
        raise ValueError("full must be a boolean")
    full_read = bool(full_arg)
    start_value, length_value = _normalize_range(arguments.get("start", 0), arguments.get("length"))

    if yield_fn:
        if full_read:
            yield_fn(
                {
                    "type": "tool_query",
                    "name": "file_read",
                    "content": f"file_id={file_id}, full=true",
                }
            )
        else:
            yield_fn(
                {
                    "type": "tool_query",
                    "name": "file_read",
                    "content": f"file_id={file_id}, start={start_value}, length={length_value}",
                }
            )

    cache: Dict[Tuple[str, int, int], Dict[str, Any]] = context.setdefault("file_chunk_cache", {})
    if full_read:
        preview_chunk = file_service.read_file_chunk(
            file_id=file_id,
            user_id=user_id,
            start=0,
            length=1,
            db=db,
        )
        total_length = max(1, int(preview_chunk.get("total_length") or 1))
        chunk = file_service.read_file_chunk(
            file_id=file_id,
            user_id=user_id,
            start=0,
            length=total_length,
            db=db,
            allow_full=True,
        )
    else:
        cache_key = (file_id, start_value, length_value)
        cached_chunk = cache.get(cache_key)
        if cached_chunk is not None:
            chunk = copy.deepcopy(cached_chunk)
        else:
            chunk = file_service.read_file_chunk(
                file_id=file_id,
                user_id=user_id,
                start=start_value,
                length=length_value,
                db=db,
            )
            cache[cache_key] = chunk
            chunk = copy.deepcopy(chunk)

    if not chunk:
        raise RuntimeError("No file chunks retrieved")

    log_event(
        logger,
        "INFO",
        "tool.file_read.range_served",
        "tool",
        file_id=file_id,
        user_id=context.get("user_id"),
        project_id=context.get("project_id"),
        conversation_id=context.get("conversation_id"),
        range_count=1,
        chunk_count=1,
        full_read=full_read,
    )

    # Query for embedded images (child files) if this is a document
    child_images = []
    if hasattr(file_record, "child_images") and file_record.child_images:
        child_images = file_record.child_images

    # If document has embedded images, include them in the response
    if child_images:
        content_blocks = []

        # Limit embedded images to avoid oversized tool payloads
        MAX_EMBEDDED_IMAGES = 20
        total_images = len(child_images)
        images_to_include = child_images[:MAX_EMBEDDED_IMAGES]
        skipped_count = max(0, total_images - MAX_EMBEDDED_IMAGES)

        if skipped_count > 0:
            log_event(
                logger,
                "INFO",
                "tool.file_read.embedded_images_limited",
                "tool",
                file_id=file_id,
                filename=file_record.original_filename,
                total_images=total_images,
                included_images=MAX_EMBEDDED_IMAGES,
            )

        # Add text content first
        base_text = f"Document: {file_record.original_filename}\n\n{chunk.get('content', '')}"

        # Add note about image limits if applicable
        if skipped_count > 0:
            base_text += f"\n\n[Note: This document contains {total_images} embedded images. Showing first {MAX_EMBEDDED_IMAGES} images. {skipped_count} additional images not displayed to stay within API limits.]"

        content_blocks.append({
            "type": "text",
            "text": base_text
        })

        # Add embedded images (resize and encode as base64)
        for idx, child_img in enumerate(images_to_include, start=1):
            try:
                # Download image from blob storage
                blob_data = blob_storage_service.get_bytes(child_img.filename)
                if not blob_data:
                    log_event(
                        logger,
                        "WARNING",
                        "tool.file_read.embedded_image_download_failed",
                        "retry",
                        file_id=file_id,
                        child_file_id=child_img.id,
                    )
                    continue

                child_file_type = (child_img.file_type or "").lower()
                image_base64, media_type = _encode_image_for_tool_content(
                    blob_data=blob_data,
                    file_type=child_file_type,
                    resize_event="tool.file_read.embedded_image_resized",
                    resize_log_fields={
                        "file_id": file_id,
                        "child_file_id": child_img.id,
                        "filename": child_img.original_filename,
                    },
                )

                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_base64,
                    },
                })
                content_blocks.append({
                    "type": "text",
                    "text": f"[Embedded Image {idx}: {child_img.original_filename}]"
                })
            except Exception as exc:
                log_event(
                    logger,
                    "WARNING",
                    "tool.file_read.embedded_image_include_failed",
                    "retry",
                    file_id=file_id,
                    child_file_id=child_img.id,
                    error=str(exc),
                )
                continue

        # Return response with content blocks (text + images)
        return {
            "_content_blocks": content_blocks,
            "file_id": chunk.get("file_id"),
            "filename": chunk.get("filename"),
            "original_filename": chunk.get("original_filename"),
            "file_type": chunk.get("file_type"),
            "has_embedded_images": True,
            "embedded_image_count": len(child_images),
        }

    # No embedded images - return text only
    return chunk

def _ensure_int(value: Any, error: str) -> int:
    """Ensure value is an integer."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
