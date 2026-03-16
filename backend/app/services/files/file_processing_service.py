"""File processing service for upload and background processing workflows."""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...config.database import call_db_method, run_db
from ...config.settings import settings
from ...database.models import File, StagedFile
from ...logging import log_event
from ...services.pii_redactor import redact_filename
from ...services.admin import analytics_event_recorder
from .blob_storage_service import blob_storage_service
from .file_processor import FileProcessor
from .project_indexing_service import (
    dispatch_project_file_index_outbox_worker,
    enqueue_project_file_index_outbox_event,
)
from .staged_processing_service import (
    dispatch_staged_file_processing_outbox_worker,
    enqueue_staged_file_processing_outbox_event,
)
from .file_service import file_service
from .staged_upload_cancellation_service import StagedUploadCancelledError

logger = logging.getLogger(__name__)


class FileProcessingService:
    """Handles file upload and processing workflows."""

    # Class-level semaphore to limit concurrent file processing (max 4 simultaneous)
    _processing_semaphore = asyncio.Semaphore(4)

    @staticmethod
    async def _is_cancelled(
        cancel_check: Optional[Callable[[], Awaitable[bool]]],
    ) -> bool:
        if cancel_check is None:
            return False
        return bool(await cancel_check())

    @classmethod
    async def _raise_if_cancelled(
        cls,
        cancel_check: Optional[Callable[[], Awaitable[bool]]],
    ) -> None:
        if await cls._is_cancelled(cancel_check):
            raise StagedUploadCancelledError("Upload cancelled by user.")

    _run_db = staticmethod(run_db)
    _call_db_method = staticmethod(call_db_method)

    @staticmethod
    def _is_async_session(db: Union[Session, AsyncSession]) -> bool:
        return isinstance(db, AsyncSession)

    async def upload_and_process_file(
        self, *, file: UploadFile, user_id: str, db: Union[Session, AsyncSession],
        conversation_id: Optional[str] = None, project_id: Optional[str] = None, redact: bool = False,
    ) -> tuple[File, dict]:
        """Complete file upload workflow with deduplication."""
        if not conversation_id and not project_id:
            raise ValueError("conversation_id or project_id must be provided")

        user_redaction_list = (
            await file_service.get_user_redaction_list_async(user_id, db)
            if redact and self._is_async_session(db)
            else (
                await self._run_db(db, lambda sync_db: file_service.get_user_redaction_list(user_id, sync_db))
                if redact
                else []
            )
        )

        async with self._processing_semaphore:
            processed_data = await FileProcessor.process_file(
                file, redact=redact, user_redaction_list=user_redaction_list,
            )
        safe_original_filename = (
            processed_data.get("original_filename")
            or file.filename
            or "unknown"
        )

        content_hash = file_service.calculate_content_hash(processed_data["file_content"], redacted=redact)

        if self._is_async_session(db):
            existing_file = await file_service.check_duplicate_file_async(
                content_hash=content_hash,
                db=db,
                project_id=project_id,
                user_id=user_id if not project_id else None,
            )
        else:
            existing_file = await self._run_db(
                db,
                lambda sync_db: file_service.check_duplicate_file(
                    content_hash=content_hash,
                    db=sync_db,
                    project_id=project_id,
                    user_id=user_id if not project_id else None,
                ),
            )

        if existing_file:
            same_scope = (
                (conversation_id and existing_file.conversation_id == conversation_id) or
                (project_id and existing_file.project_id == project_id and existing_file.user_id == user_id)
            )
            if same_scope:
                if redact and existing_file.original_filename != safe_original_filename:
                    existing_file.original_filename = safe_original_filename
                    await self._call_db_method(db, "commit")
                    existing_file = (
                        await file_service.get_file_by_id_async(
                            str(existing_file.id),
                            user_id,
                            db,
                            include_text=True,
                            include_uploader=bool(project_id),
                        )
                        if self._is_async_session(db)
                        else await self._run_db(
                            db,
                            lambda sync_db: file_service.get_file_by_id(
                                str(existing_file.id),
                                user_id,
                                sync_db,
                                include_text=True,
                                include_uploader=bool(project_id),
                            ),
                        )
                    ) or existing_file
                return existing_file, processed_data
            log_event(
                logger,
                "INFO",
                "file.upload.duplicate_scope_creates_new_blob",
                "tool",
                user_id=user_id,
                conversation_id=conversation_id,
                project_id=project_id,
                existing_file_id=str(existing_file.id),
            )

        system_filename = file_service.generate_filename(file.filename or "unknown", user_id)
        blob_url = await blob_storage_service.upload(system_filename, processed_data["file_content"])
        uploaded_new_blob = True

        try:
            file_record = await self._run_db(
                db,
                lambda sync_db: file_service.create_file_record(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    project_id=project_id,
                    storage_key=system_filename,
                    original_filename=safe_original_filename,
                    file_type=processed_data["file_type"],
                    file_size=processed_data["file_size"],
                    content_hash=content_hash,
                    blob_url=blob_url,
                    extracted_text=processed_data["extracted_text"],
                    db=sync_db,
                    commit=False,
                ),
            )
            await self._call_db_method(db, "flush")

            # Record redaction stats if redaction was actually applied.
            # Analytics failures must not break user-facing upload flow.
            if processed_data.get("redaction_performed"):
                try:
                    await self._run_db(
                        db,
                        lambda sync_db: analytics_event_recorder.record_redaction_applied(
                            sync_db,
                            user_id,
                            target_id=str(file_record.id),
                        ),
                    )
                except Exception as exc:
                    log_event(
                        logger,
                        "WARNING",
                        "file.upload.redaction_analytics_record_failed",
                        "retry",
                        user_id=user_id,
                        conversation_id=conversation_id,
                        project_id=project_id,
                        file_id=str(file_record.id),
                        exc_info=exc,
                    )

            await self._call_db_method(db, "commit")
            file_record = (
                await file_service.get_file_by_id_async(
                    str(file_record.id),
                    user_id,
                    db,
                    include_text=True,
                    include_uploader=bool(project_id),
                )
                if self._is_async_session(db)
                else await self._run_db(
                    db,
                    lambda sync_db: file_service.get_file_by_id(
                        str(file_record.id),
                        user_id,
                        sync_db,
                        include_text=True,
                        include_uploader=bool(project_id),
                    ),
                )
            ) or file_record
            return file_record, processed_data
        except IntegrityError:
            await self._call_db_method(db, "rollback")
            recovered = (
                await file_service.get_scope_file_by_hash_async(
                    db=db,
                    content_hash=content_hash,
                    conversation_id=conversation_id,
                    project_id=project_id,
                )
                if self._is_async_session(db)
                else await self._run_db(
                    db,
                    lambda sync_db: file_service.get_scope_file_by_hash(
                        db=sync_db,
                        content_hash=content_hash,
                        conversation_id=conversation_id,
                        project_id=project_id,
                    ),
                )
            )
            if uploaded_new_blob and blob_storage_service.blob_client:
                blob_storage_service.delete(system_filename)
            if recovered:
                return recovered, processed_data
            raise

    async def upload_file_for_background_processing(
        self,
        *,
        file: UploadFile,
        user_id: str,
        db: Union[Session, AsyncSession],
        project_id: str,
        redact: bool = False,
    ) -> File:
        """Upload a project file and process indexing via the durable outbox in-process."""
        from anyio import to_thread
        from .file_processor import IMAGE_EXTENSIONS

        file_type = await FileProcessor.validate_file(file)
        user_redaction_list = (
            await file_service.get_user_redaction_list_async(user_id, db)
            if redact and self._is_async_session(db)
            else (
                await self._run_db(db, lambda sync_db: file_service.get_user_redaction_list(user_id, sync_db))
                if redact
                else []
            )
        )
        safe_original_filename = file.filename or "unknown"
        if redact:
            filename_result = redact_filename(
                safe_original_filename,
                user_redaction_list=user_redaction_list,
            )
            safe_original_filename = filename_result.text

        file_bytes_for_upload: Optional[bytes] = None
        file_obj = getattr(file, "file", None)
        can_stream_fileobj = bool(
            file_obj is not None
            and hasattr(file_obj, "read")
            and hasattr(file_obj, "seek")
        )
        content_hash: str
        content_size: int
        spreadsheet_redaction_performed = False
        spreadsheet_redaction_hits: List[str] = []

        if redact and FileProcessor.is_spreadsheet_type(file_type):
            if not FileProcessor.supports_spreadsheet_byte_redaction(file_type):
                raise ValueError(
                    "Redaction for this spreadsheet format is not supported yet. "
                    "Use XLSX, XLSM, CSV, or TSV for redacted uploads."
                )
            spreadsheet_bytes = await file.read()
            spreadsheet_redaction_result = await FileProcessor.redact_spreadsheet_file_content(
                spreadsheet_bytes,
                file_type,
                user_redaction_list=user_redaction_list,
            )
            file_bytes_for_upload = spreadsheet_redaction_result.file_content
            content_size = len(file_bytes_for_upload)
            spreadsheet_redaction_performed = spreadsheet_redaction_result.redaction_performed
            spreadsheet_redaction_hits = spreadsheet_redaction_result.redaction_hits
            content_hash = file_service.calculate_content_hash(
                file_bytes_for_upload,
                redacted=redact,
            )
            if spreadsheet_redaction_performed:
                log_event(
                    logger,
                    "INFO",
                    "redaction.spreadsheet_bytes_applied",
                    "timing",
                    user_id=user_id,
                    project_id=project_id,
                    filename=file.filename,
                    file_type=file_type,
                    redaction_hits=spreadsheet_redaction_hits,
                )
        elif file_type in IMAGE_EXTENSIONS:
            file_content = await file.read()
            content_size = len(file_content)

            normalized = await to_thread.run_sync(
                FileProcessor._normalize_image,
                file_content,
                file_type,
            )
            if normalized:
                file_content, file_type = normalized
                content_size = len(file_content)
            file_bytes_for_upload = file_content
            content_hash = file_service.calculate_content_hash(file_content, redacted=redact)
        else:
            if can_stream_fileobj:
                content_hash, content_size = await to_thread.run_sync(
                    lambda: file_service.calculate_content_hash_from_fileobj(
                        file_obj,
                        redacted=redact,
                    )
                )
            else:
                file_content = await file.read()
                content_size = len(file_content)
                file_bytes_for_upload = file_content
                content_hash = file_service.calculate_content_hash(file_content, redacted=redact)

        max_size = settings.max_file_size
        if max_size and content_size > max_size:
            from fastapi import HTTPException
            raise HTTPException(status_code=413, detail=f"File size exceeds {max_size / 1024 / 1024:.0f}MB")

        await file.seek(0)

        existing_file = (
            await file_service.check_duplicate_file_async(
                content_hash=content_hash,
                project_id=project_id,
                db=db,
            )
            if self._is_async_session(db)
            else await self._run_db(
                db,
                lambda sync_db: file_service.check_duplicate_file(
                    content_hash=content_hash,
                    project_id=project_id,
                    db=sync_db,
                ),
            )
        )
        if existing_file and existing_file.project_id == project_id:
            if existing_file.processing_status != "completed":
                await self._run_db(
                    db,
                    lambda sync_db: enqueue_project_file_index_outbox_event(
                        db=sync_db,
                        file_id=str(existing_file.id),
                        project_id=project_id,
                        payload={
                            "reason": "duplicate_reupload_retry",
                            "redact": bool(redact),
                            "user_redaction_list": list(user_redaction_list),
                        },
                    ),
                )
                await self._call_db_method(db, "commit")
                await asyncio.to_thread(dispatch_project_file_index_outbox_worker)
                log_event(
                    logger,
                    "INFO",
                    "project.file_upload.reused_pending_file",
                    "tool",
                    user_id=user_id,
                    project_id=project_id,
                    file_id=str(existing_file.id),
                    processing_status=existing_file.processing_status,
                    redaction_requested=bool(redact),
                )
            else:
                log_event(
                    logger,
                    "INFO",
                    "project.file_upload.reused_completed_file",
                    "tool",
                    user_id=user_id,
                    project_id=project_id,
                    file_id=str(existing_file.id),
                    processing_status=existing_file.processing_status,
                    redaction_requested=bool(redact),
                )
            return existing_file

        system_filename = file_service.generate_filename(file.filename or "unknown", user_id)
        if file_bytes_for_upload is not None:
            blob_url = await blob_storage_service.upload(system_filename, file_bytes_for_upload)
        else:
            blob_url = await blob_storage_service.upload_fileobj(system_filename, file_obj)
        uploaded_new_blob = True

        try:
            file_record = await self._run_db(
                db,
                lambda sync_db: file_service.create_file_record(
                    user_id=user_id,
                    project_id=project_id,
                    storage_key=system_filename,
                    original_filename=safe_original_filename,
                    file_type=file_type,
                    file_size=content_size,
                    content_hash=content_hash,
                    blob_url=blob_url,
                    extracted_text=None,
                    db=sync_db,
                    commit=False,
                    processing_status="pending",
                ),
            )
            file_record.indexed_chunk_count = 0
            file_record.indexed_at = None
            file_record.processing_error = None
            await self._run_db(
                db,
                lambda sync_db: enqueue_project_file_index_outbox_event(
                    db=sync_db,
                    file_id=str(file_record.id),
                    project_id=project_id,
                    payload={
                        "uploaded_by": user_id,
                        "filename": safe_original_filename,
                        "redact": bool(redact),
                        "user_redaction_list": list(user_redaction_list),
                    },
                ),
            )
            await self._call_db_method(db, "flush")
            await self._call_db_method(db, "commit")
            try:
                file_record = (
                    await file_service.get_file_by_id_async(
                        str(file_record.id),
                        user_id,
                        db,
                        include_text=True,
                        include_uploader=True,
                    )
                    if self._is_async_session(db)
                    else await self._run_db(
                        db,
                        lambda sync_db: file_service.get_file_by_id(
                            str(file_record.id),
                            user_id,
                            sync_db,
                            include_text=True,
                            include_uploader=True,
                        ),
                    )
                ) or file_record
            except AttributeError:
                pass
            log_event(
                logger,
                "INFO",
                "project.file_upload.accepted",
                "tool",
                user_id=user_id,
                project_id=project_id,
                file_id=str(file_record.id),
                filename=safe_original_filename,
                processing_status=file_record.processing_status,
                redaction_requested=bool(redact),
            )
            log_event(
                logger,
                "INFO",
                "project.file_index.outbox_queued",
                "tool",
                user_id=user_id,
                project_id=project_id,
                file_id=str(file_record.id),
            )
            await asyncio.to_thread(dispatch_project_file_index_outbox_worker)
            return file_record
        except IntegrityError:
            await self._call_db_method(db, "rollback")
            recovered = (
                await file_service.get_scope_file_by_hash_async(
                    db=db,
                    content_hash=content_hash,
                    project_id=project_id,
                )
                if self._is_async_session(db)
                else await self._run_db(
                    db,
                    lambda sync_db: file_service.get_scope_file_by_hash(
                        db=sync_db,
                        content_hash=content_hash,
                        project_id=project_id,
                    ),
                )
            )
            if uploaded_new_blob and blob_storage_service.blob_client:
                blob_storage_service.delete(system_filename)
            if recovered:
                return recovered
            raise

    async def upload_and_process_staged_file(
        self, *, file: UploadFile, user_id: str, db: Union[Session, AsyncSession],
        draft_id: Optional[str] = None, redact: bool = False,
        cancel_check: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> StagedFile:
        """Upload a staged file and process text extraction via the durable outbox in-process."""
        from anyio import to_thread
        from .file_processor import IMAGE_EXTENSIONS

        await self._raise_if_cancelled(cancel_check)
        file_type = await FileProcessor.validate_file(file)
        user_redaction_list = (
            await file_service.get_user_redaction_list_async(user_id, db)
            if redact and self._is_async_session(db)
            else (
                await self._run_db(db, lambda sync_db: file_service.get_user_redaction_list(user_id, sync_db))
                if redact
                else []
            )
        )
        safe_original_filename = file.filename or "unknown"
        filename_redaction_performed = False
        if redact:
            filename_result = redact_filename(
                safe_original_filename,
                user_redaction_list=user_redaction_list,
            )
            safe_original_filename = filename_result.text
            filename_redaction_performed = bool(filename_result.redaction_performed)

        file_bytes_for_upload: Optional[bytes] = None
        file_obj = getattr(file, "file", None)
        can_stream_fileobj = bool(file_obj is not None and hasattr(file_obj, "read") and hasattr(file_obj, "seek"))
        content_hash: str
        content_size: int
        spreadsheet_redaction_performed = False

        if redact and FileProcessor.is_spreadsheet_type(file_type):
            if not FileProcessor.supports_spreadsheet_byte_redaction(file_type):
                raise ValueError(
                    "Redaction for this spreadsheet format is not supported yet. "
                    "Use XLSX, XLSM, CSV, or TSV for redacted uploads."
                )
            spreadsheet_bytes = await file.read()
            spreadsheet_redaction_result = await FileProcessor.redact_spreadsheet_file_content(
                spreadsheet_bytes,
                file_type,
                user_redaction_list=user_redaction_list,
            )
            file_bytes_for_upload = spreadsheet_redaction_result.file_content
            content_size = len(file_bytes_for_upload)
            spreadsheet_redaction_performed = bool(spreadsheet_redaction_result.redaction_performed)
            content_hash = file_service.calculate_content_hash(file_bytes_for_upload, redacted=redact)
        elif file_type in IMAGE_EXTENSIONS:
            file_content = await file.read()
            content_size = len(file_content)
            normalized = await to_thread.run_sync(
                FileProcessor._normalize_image,
                file_content,
                file_type,
            )
            if normalized:
                file_content, file_type = normalized
                content_size = len(file_content)
            file_bytes_for_upload = file_content
            content_hash = file_service.calculate_content_hash(file_content, redacted=redact)
        else:
            if can_stream_fileobj:
                content_hash, content_size = await to_thread.run_sync(
                    lambda: file_service.calculate_content_hash_from_fileobj(
                        file_obj,
                        redacted=redact,
                    )
                )
            else:
                file_content = await file.read()
                content_size = len(file_content)
                file_bytes_for_upload = file_content
                content_hash = file_service.calculate_content_hash(file_content, redacted=redact)

        max_size = settings.max_file_size
        if max_size and content_size > max_size:
            from fastapi import HTTPException

            raise HTTPException(status_code=413, detail=f"File size exceeds {max_size / 1024 / 1024:.0f}MB")

        await file.seek(0)
        await self._raise_if_cancelled(cancel_check)

        existing = (
            await file_service.check_duplicate_staged_async(content_hash, user_id, db)
            if self._is_async_session(db)
            else await self._run_db(
                db,
                lambda sync_db: file_service.check_duplicate_staged(content_hash, user_id, sync_db),
            )
        )
        if existing:
            changed = False
            if redact and existing.original_filename != safe_original_filename:
                existing.original_filename = safe_original_filename
                changed = True
            if draft_id and existing.draft_id != draft_id:
                existing.draft_id = draft_id
                changed = True
            if changed:
                await self._call_db_method(db, "commit")
                existing = (
                    await file_service.get_staged_by_id_async(str(existing.id), user_id, db)
                    if self._is_async_session(db)
                    else await self._run_db(
                        db,
                        lambda sync_db: file_service.get_staged_by_id(str(existing.id), user_id, sync_db),
                    )
                ) or existing
            return existing

        system_filename = file_service.generate_filename(file.filename or "unknown", user_id)
        if file_bytes_for_upload is not None:
            blob_url = await blob_storage_service.upload(system_filename, file_bytes_for_upload)
        else:
            blob_url = await blob_storage_service.upload_fileobj(system_filename, file_obj)
        uploaded_new_blob = True

        try:
            staged = await self._run_db(
                db,
                lambda sync_db: file_service.create_staged_file_record(
                    user_id=user_id,
                    storage_key=system_filename,
                    original_filename=safe_original_filename,
                    file_type=file_type,
                    file_size=content_size,
                    content_hash=content_hash,
                    blob_url=blob_url,
                    extracted_text=None,
                    draft_id=draft_id,
                    db=sync_db,
                    commit=False,
                    processing_status="pending",
                    processing_error=None,
                    redaction_requested=bool(redact),
                    redaction_applied=bool(filename_redaction_performed or spreadsheet_redaction_performed),
                    redacted_categories=["user_redaction"] if (filename_redaction_performed or spreadsheet_redaction_performed) else [],
                ),
            )
            await self._run_db(
                db,
                lambda sync_db: enqueue_staged_file_processing_outbox_event(
                    db=sync_db,
                    staged_file_id=str(staged.id),
                    user_id=user_id,
                    payload={
                        "redact": bool(redact),
                        "user_redaction_list": list(user_redaction_list),
                    },
                ),
            )
            await self._call_db_method(db, "flush")

            if filename_redaction_performed or spreadsheet_redaction_performed:
                try:
                    await self._run_db(
                        db,
                        lambda sync_db: analytics_event_recorder.record_redaction_applied(
                            sync_db,
                            user_id,
                            target_id=str(staged.id),
                        ),
                    )
                except Exception as exc:
                    log_event(
                        logger,
                        "WARNING",
                        "file.staged_upload.redaction_analytics_record_failed",
                        "retry",
                        user_id=user_id,
                        draft_id=draft_id,
                        staged_file_id=str(staged.id),
                        exc_info=exc,
                    )

            await self._call_db_method(db, "commit")
            try:
                staged = (
                    await file_service.get_staged_by_id_async(str(staged.id), user_id, db)
                    if self._is_async_session(db)
                    else await self._run_db(
                        db,
                        lambda sync_db: file_service.get_staged_by_id(str(staged.id), user_id, sync_db),
                    )
                ) or staged
            except AttributeError:
                pass
            await asyncio.to_thread(dispatch_staged_file_processing_outbox_worker)
            return staged
        except IntegrityError:
            await self._call_db_method(db, "rollback")
            recovered = (
                await file_service.check_duplicate_staged_async(content_hash, user_id, db)
                if self._is_async_session(db)
                else await self._run_db(
                    db,
                    lambda sync_db: file_service.check_duplicate_staged(content_hash, user_id, sync_db),
                )
            )
            if uploaded_new_blob and blob_storage_service.blob_client:
                blob_storage_service.delete(system_filename)
            if recovered:
                return recovered
            raise
        except StagedUploadCancelledError:
            await self._call_db_method(db, "rollback")
            if uploaded_new_blob and blob_storage_service.blob_client:
                blob_storage_service.delete(system_filename)
            raise


# Singleton instance
file_processing_service = FileProcessingService()
