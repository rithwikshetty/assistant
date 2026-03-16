import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config.database import get_async_db as get_db, run_db as _run_db
from ..database.models import User
from ..logging import log_event
from ..services.files import (
    file_service,
    file_processing_service,
)
from ..schemas.files import StagedFileDeleteResponse, StagedFileResponse, StagedUploadCancelResponse

router = APIRouter(prefix="/staged-files", tags=["staged-files"])
logger = logging.getLogger(__name__)


def _serialize_staged_file(staged) -> StagedFileResponse:
    return StagedFileResponse(
        id=staged.id,
        filename=staged.filename,
        original_filename=staged.original_filename,
        file_type=staged.file_type,
        file_size=staged.file_size,
        created_at=staged.created_at,
        processing_status=getattr(staged, "processing_status", "pending"),
        processing_error=getattr(staged, "processing_error", None),
        redaction_requested=bool(getattr(staged, "redaction_requested", False)),
        redaction_applied=bool(getattr(staged, "redaction_applied", False)),
        redacted_categories=list(getattr(staged, "redacted_categories_jsonb", []) or []),
        extracted_text=getattr(staged, "extracted_text", None),
    )


@router.post("/upload", response_model=StagedFileResponse)
async def upload_staged_file(
    file: UploadFile = FastAPIFile(...),
    draft_id: str | None = None,
    redact: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a file into staging and process it asynchronously."""
    try:
        staged = await file_processing_service.upload_and_process_staged_file(
            file=file,
            user_id=user.id,
            db=db,
            draft_id=draft_id,
            redact=redact,
        )
        return _serialize_staged_file(staged)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{staged_id}", response_model=StagedFileResponse)
async def get_staged_file(
    staged_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    staged = await _run_db(
        db,
        lambda sync_db: file_service.get_staged_by_id(staged_id, user.id, sync_db),
    )
    if not staged:
        raise HTTPException(status_code=404, detail="Staged file not found")
    return _serialize_staged_file(staged)


@router.post("/uploads/{upload_id}/cancel", response_model=StagedUploadCancelResponse)
async def cancel_staged_upload(
    upload_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete staged files associated with an upload draft id."""
    removed = await _run_db(
        db,
        lambda sync_db: file_service.delete_staged_files_by_draft_id(upload_id, user.id, sync_db),
    )
    log_event(
        logger,
        "INFO",
        "file.staged_upload.cancel_requested",
        "timing",
        user_id=user.id,
        upload_id=upload_id,
        staged_files_removed=removed,
    )
    return StagedUploadCancelResponse(
        status="cancelled",
        staged_files_removed=removed,
    )


@router.delete("/{staged_id}", response_model=StagedFileDeleteResponse)
async def delete_staged_file(
    staged_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a staged file (and its blob)."""
    ok = await _run_db(
        db,
        lambda sync_db: file_service.delete_staged_file(staged_id, user.id, sync_db),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Staged file not found")
    return StagedFileDeleteResponse(message="Staged file deleted")
