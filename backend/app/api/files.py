import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..auth.dependencies import get_current_user
from ..config.database import get_async_db as get_db, run_db as _run_db
from ..database.models import User, Conversation
from ..logging import log_event
from ..services.files import (
    file_service,
    file_processing_service,
    file_search_service,
    blob_storage_service,
)
from ..schemas.files import (
    FileUploadResponse,
    FileInfo,
    FileQueryRequest,
    FileQueryResponse,
    ConversationFilesResponse,
    FileContentChunkResponse,
    FileDeleteResponse,
    FileDownloadResponse,
)
from ..config.settings import settings

router = APIRouter(prefix="/files", tags=["files"])
logger = logging.getLogger(__name__)


@router.get("/blob/{blob_path:path}")
async def download_blob_file(
    blob_path: str,
    download_name: str | None = None,
):
    """Serve locally stored file bytes through the backend."""
    try:
        resolved = blob_storage_service._resolve_path(unquote(blob_path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")

    filename = download_name or resolved.name
    return FileResponse(path=resolved, filename=filename)


@router.post("/upload/{conversation_id}", response_model=FileUploadResponse)
async def upload_file(
    conversation_id: str,
    file: UploadFile = FastAPIFile(...),
    redact: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file to a conversation and extract its text content."""
    try:
        conversation = await _run_db(
            db,
            lambda sync_db: (
                sync_db.query(Conversation)
                .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
                .first()
            ),
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        file_record, processed = await file_processing_service.upload_and_process_file(
            file=file,
            user_id=user.id,
            conversation_id=conversation_id,
            db=db,
            redact=redact,
        )
        
        return FileUploadResponse(
            id=file_record.id,
            filename=file_record.filename,
            original_filename=file_record.original_filename,
            file_type=file_record.file_type,
            file_size=file_record.file_size,
            created_at=file_record.created_at,
            redaction_applied=processed.get("redaction_performed", False),
            redaction_requested=processed.get("redaction_requested", False),
            redacted_categories=processed.get("redacted_categories", []),
            user_redaction_applied=processed.get(
                "user_redaction_performed",
                processed.get("redaction_performed", False),
            ),
            user_redaction_hits=processed.get(
                "user_redaction_hits",
                processed.get("redaction_hits", []),
            ),
            extracted_text=processed.get("extracted_text"),
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "files.upload.failed",
            "error",
            user_id=str(user.id),
            conversation_id=conversation_id,
            filename=file.filename,
            content_type=file.content_type,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=400, detail="Failed to upload file")

@router.get("/conversation/{conversation_id}", response_model=ConversationFilesResponse)
async def get_conversation_files(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all files for a conversation."""
    stats = await _run_db(
        db,
        lambda sync_db: file_service.get_conversation_files_stats(conversation_id, user.id, sync_db),
    )
    
    files_info = [
        FileInfo(
            id=file.id,
            filename=file.filename,
            original_filename=file.original_filename,
            file_type=file.file_type,
            file_size=file.file_size,
            blob_url=file.blob_url,
            created_at=file.created_at,
            updated_at=file.updated_at
        )
        for file in stats["files"]
    ]
    
    return ConversationFilesResponse(
        total_files=stats["total_files"],
        total_size=stats["total_size"],
        files=files_info
    )

@router.post("/search", response_model=FileQueryResponse)
async def search_files(
    search_request: FileQueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search through file content in a conversation."""
    results = await _run_db(
        db,
        lambda sync_db: file_search_service.search_conversation_files(
            query=search_request.query,
            conversation_id=search_request.conversation_id,
            user_id=user.id,
            db=sync_db,
        ),
    )
    
    return FileQueryResponse(
        files_found=len(results),
        results=results
    )

@router.get("/{file_id}", response_model=FileInfo)
async def get_file_info(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get information about a specific file."""
    file_record = await _run_db(
        db,
        lambda sync_db: file_service.get_file_by_id(file_id, user.id, sync_db),
    )
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileInfo(
        id=file_record.id,
        filename=file_record.filename,
        original_filename=file_record.original_filename,
        file_type=file_record.file_type,
        file_size=file_record.file_size,
        blob_url=file_record.blob_url,
        created_at=file_record.created_at,
        updated_at=file_record.updated_at
    )

@router.get("/{file_id}/download", response_model=FileDownloadResponse)
async def get_download_url(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the download URL for a file."""
    file_record = await _run_db(
        db,
        lambda sync_db: file_service.get_file_by_id(file_id, user.id, sync_db),
    )
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    if not file_record.filename:
        raise HTTPException(status_code=410, detail="File content has been purged")

    try:
        download_url = blob_storage_service.build_sas_url(
            filename=file_record.filename,
            expiry_minutes=10080,  # 7 days
            original_filename=file_record.original_filename,
        )
    except Exception:
        # Best-effort fallback
        download_url = file_record.blob_url

    return FileDownloadResponse(
        download_url=download_url,
        filename=file_record.original_filename,
        file_type=file_record.file_type,
        expires_in_days=7,
        expires_in_minutes=10080,
    )

@router.get("/{file_id}/content", response_model=FileContentChunkResponse)
async def get_file_content_chunk(
    file_id: str,
    start: int = Query(0, ge=0, description="Start offset for the chunk."),
    length: int = Query(
        settings.file_chunk_max_length,
        gt=0,
        description="Number of characters (or bytes fallback) to return in the chunk.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a chunk of file content for progressive loading in the chat UI."""
    try:
        chunk = await _run_db(
            db,
            lambda sync_db: file_service.read_file_chunk(
                file_id=file_id,
                user_id=user.id,
                start=start,
                length=length,
                db=sync_db,
            ),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        if str(exc) == "File content has been purged":
            raise HTTPException(status_code=410, detail=str(exc))
        raise HTTPException(status_code=503, detail=str(exc))

    return chunk

@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file."""
    success = await _run_db(
        db,
        lambda sync_db: file_service.delete_file(file_id, user.id, sync_db),
    )
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileDeleteResponse(message="File deleted successfully")

# Utility endpoint for file content search across all user's files
@router.post("/search/all", response_model=FileQueryResponse)
async def search_all_files(
    query: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search through all user's file content across all conversations."""
    # This could be useful for global file search
    # Implementation would be similar but without conversation_id filter
    # For now, we'll require conversation_id for performance
    raise HTTPException(
        status_code=501, 
        detail="Global file search not implemented. Please search within a specific conversation."
    )
