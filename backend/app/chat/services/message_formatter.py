"""Message formatting utilities for attachments and context."""
import logging
import re
from typing import Dict, Any, List, Optional, Set
from ...config.settings import settings
from ...config.file_types import SPREADSHEET_EXTENSIONS
from ...logging import log_event
from ...services.files import blob_storage_service

logger = logging.getLogger(__name__)

# Image MIME types and extensions supported by chat backends
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/jpg"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def sanitize_message_content_for_model_input(content: str, conversation_id: Optional[str] = None) -> str:
    """Remove or replace problematic URLs that model backends may try to download.

    When users paste content from Excel/Word, clipboard data may contain:
    - file:// URLs (local file paths)
    - Inaccessible SharePoint/OneDrive links
    - Embedded hyperlinks that providers may attempt to download

    This can cause provider download errors (400) for external file references.

    Args:
        content: Raw message content
        conversation_id: Optional conversation ID for logging context

    Returns:
        Sanitized content with problematic URLs replaced
    """
    if not content or not isinstance(content, str):
        return content

    original_content = content
    urls_stripped = []

    # Pattern 1: file:// URLs (local paths from Word/Excel)
    file_url_pattern = r'file://[^\s<>"{}|\\^`\[\]]+'
    file_urls = re.findall(file_url_pattern, content)
    if file_urls:
        urls_stripped.extend(file_urls)
        content = re.sub(file_url_pattern, '[local file reference removed]', content)

    # Pattern 2: Data URIs (base64 encoded images/files from paste)
    # These can be very long and cause issues
    data_uri_pattern = r'data:[^;]+;base64,[A-Za-z0-9+/=]{100,}'
    data_uris = re.findall(data_uri_pattern, content)
    if data_uris:
        log_event(
            logger,
            "INFO",
            "chat.message.sanitized_data_uri",
            "timing",
            data_uri_count=len(data_uris),
            conversation_id=conversation_id,
        )
        content = re.sub(data_uri_pattern, '[embedded data removed]', content)

    # Log sanitization for debugging
    if urls_stripped:
        log_event(
            logger,
            "WARNING",
            "chat.message.sanitized_urls",
            "retry",
            url_count=len(urls_stripped),
            conversation_id=conversation_id,
            url_types=[url.split(":")[0] + "://" for url in urls_stripped[:5]],
        )

    return content

def format_attachment_summary(attachments: List[Dict[str, Any]]) -> str:
    """Format a summary of attachments for display to the AI.

    Images are sent as visual content blocks AND listed here with their file_ids
    so the model can reference them for editing or other operations.
    """
    if not attachments:
        return ""

    image_lines: List[str] = []
    data_lines: List[str] = []
    document_lines: List[str] = []
    image_index = 1
    data_index = 1
    doc_index = 1

    for att in attachments:
        file_id = att.get("id")
        name = att.get("original_filename") or att.get("filename") or "attachment"
        file_type = att.get("file_type") or att.get("mime_type") or ""
        size = att.get("file_size")
        size_part = f", {size} bytes" if isinstance(size, int) else ""
        type_part = f" ({file_type})" if file_type else ""

        if is_image_attachment(att):
            if isinstance(file_id, str):
                image_lines.append(f"{image_index}. {name}{type_part}{size_part} — file_id: {file_id}")
            else:
                image_lines.append(f"{image_index}. {name}{type_part}{size_part}")
            image_index += 1
        elif file_type.lower() in SPREADSHEET_EXTENSIONS:
            # Data files → route to execute_code for pandas analysis
            if isinstance(file_id, str):
                data_lines.append(f"{data_index}. {name}{type_part}{size_part} — file_id: {file_id}")
            else:
                data_lines.append(f"{data_index}. {name}{type_part}{size_part}")
            data_index += 1
        else:
            if isinstance(file_id, str):
                document_lines.append(f"{doc_index}. {name}{type_part}{size_part} — file_id: {file_id}")
            else:
                document_lines.append(f"{doc_index}. {name}{type_part}{size_part}")
            doc_index += 1

    if not image_lines and not data_lines and not document_lines:
        return ""

    parts: List[str] = []

    if image_lines:
        image_instructions = (
            "Images (displayed above):\n" + "\n".join(image_lines)
        )
        parts.append(image_instructions)

    if data_lines:
        data_instructions = (
            "Data files (spreadsheets):\n" + "\n".join(data_lines) + "\n"
            "Use the `execute_code` tool with the `file_ids` parameter to analyse these files with pandas. "
            "The files will be available in INPUT_DIR inside the sandbox. "
            "You can also use `file_read` to see a quick metadata preview (columns, sample rows)."
        )
        parts.append(data_instructions)

    if document_lines:
        chunk_limit = settings.file_chunk_max_length or 50000
        doc_instructions = (
            "Attached files:\n" + "\n".join(document_lines) + "\n" +
            f"Use the `file_read` tool with the `file_id` to read the file's contents. "
            f"Request chunks with `start` and `length` (recommended length ≤ {chunk_limit})."
        )
        parts.append(doc_instructions)

    return "\n\n".join(parts)


def append_attachment_context(
    message_text: str,
    attachments: List[Dict[str, Any]],
    collector: Optional[Set[str]] = None,
) -> str:
    """Append attachment context to a message and collect allowed file IDs."""
    if not attachments:
        return message_text

    if collector is not None:
        for att in attachments:
            file_id = att.get("id")
            if isinstance(file_id, str):
                collector.add(file_id)

    summary = format_attachment_summary(attachments)
    if not summary:
        return message_text

    base = message_text.rstrip()
    if base:
        return f"{base}\n\n{summary}"
    return summary


def is_image_attachment(attachment: Dict[str, Any]) -> bool:
    """Check if an attachment is an image based on file type (MIME type or extension)."""
    file_type = attachment.get("file_type", "").lower()
    # Check both MIME types (image/png) and extensions (png)
    return file_type in IMAGE_MIME_TYPES or file_type in IMAGE_EXTENSIONS


def build_image_content_blocks(
    attachments: List[Dict[str, Any]],
    file_service: Any,
) -> List[Dict[str, Any]]:
    """Build image content blocks using direct backend file URLs.

    Only handles directly uploaded image files (PNG, JPG, JPEG, GIF, WEBP).
    Document images are now handled by LlamaParse text extraction.

    This avoids downloading and re-encoding images on the server path and
    lets the provider fetch images directly from the backend file endpoint.
    """
    # Map file extensions to MIME types for provider image inputs.
    EXTENSION_TO_MIME = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }

    image_blocks: List[Dict[str, Any]] = []

    # Direct image attachments only
    for att in attachments:
        if not is_image_attachment(att):
            continue

        filename = att.get("filename")
        file_type = (att.get("file_type") or "").lower()
        original = att.get("original_filename")
        if not filename:
            continue

        # Determine media type
        if file_type in IMAGE_EXTENSIONS:
            media_type = EXTENSION_TO_MIME.get(file_type, "image/jpeg")
        else:
            media_type = file_type if file_type in IMAGE_MIME_TYPES else "image/jpeg"

        try:
            # Generate a SAS URL (7 days default; good for share + chat replay)
            sas_url = blob_storage_service.build_sas_url(
                filename=filename,
                original_filename=original,
                expiry_minutes=10080,
            )
            image_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": sas_url,
                    },
                }
            )
        except Exception:
            # Best-effort: if SAS generation fails, fall back to plain blob URL (if available)
            fallback_url = att.get("blob_url")
            if isinstance(fallback_url, str) and fallback_url.strip():
                image_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": fallback_url,
                        },
                    }
                )

    return image_blocks
