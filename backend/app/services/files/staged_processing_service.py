"""Staged attachment processing via durable outbox handled in-process."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ...config.database import SessionLocal
from ...config.settings import settings
from ...database.models import StagedFile, StagedFileProcessingOutbox
from ...logging import log_event
from ...services.pii_redactor import redact_text
from .blob_storage_service import blob_storage_service
from .file_constants import IMAGE_EXTENSIONS
from .file_processor import FileProcessor

logger = logging.getLogger(__name__)

STAGED_FILE_PROCESS_EVENT_TYPE = "staged.file.process.requested"
STAGED_FILE_PROCESS_EVENT_VERSION = 1
STAGED_FILE_PROCESS_TASK_NAME = "app.staged_files.process_outbox_batch"
NON_RETRYABLE_STAGED_ERRORS: tuple[str, ...] = (
    "failed to load file bytes from blob storage",
    "staged file not found",
    "llamaparse api key not configured",
)


def enqueue_staged_file_processing_outbox_event(
    *,
    db: Session,
    staged_file_id: str,
    user_id: str,
    payload: Dict[str, Any] | None = None,
) -> StagedFileProcessingOutbox:
    row = StagedFileProcessingOutbox(
        event_type=STAGED_FILE_PROCESS_EVENT_TYPE,
        event_version=STAGED_FILE_PROCESS_EVENT_VERSION,
        staged_file_id=staged_file_id,
        user_id=user_id,
        payload_jsonb=payload or {},
    )
    db.add(row)
    return row


def dispatch_staged_file_processing_outbox_worker(
    *,
    batch_size: int | None = None,
) -> None:
    resolved_batch_size = max(
        1,
        int(batch_size or getattr(settings, "staged_file_processing_outbox_batch_size", 100) or 100),
    )
    db = SessionLocal()
    try:
        outcome = process_staged_file_processing_outbox_batch_sync(
            db,
            batch_size=resolved_batch_size,
        )
        db.commit()
        log_event(
            logger,
            "INFO",
            "staged.file_processing.outbox_batch.processed_inline",
            "final",
            batch_size=resolved_batch_size,
            scanned=int(outcome.get("scanned", 0)),
            processed=int(outcome.get("processed", 0)),
            errors=int(outcome.get("errors", 0)),
        )
    except OperationalError as exc:
        db.rollback()
        log_event(
            logger,
            "WARNING",
            "staged.file_processing.outbox_batch.inline_db_failed",
            "retry",
            task_name=STAGED_FILE_PROCESS_TASK_NAME,
            batch_size=resolved_batch_size,
            exc_info=exc,
        )
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "WARNING",
            "staged.file_processing.outbox_batch.inline_failed",
            "retry",
            task_name=STAGED_FILE_PROCESS_TASK_NAME,
            batch_size=resolved_batch_size,
            exc_info=exc,
        )
    finally:
        db.close()


def _run_async_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _normalize_extracted_text(raw_text: Any) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    if lowered.startswith("failed to extract text from "):
        raise RuntimeError(text[:512])
    if lowered.startswith("llamaparse api key not configured"):
        raise ValueError("LlamaParse API key not configured")
    if lowered.startswith("no readable text content found in "):
        return ""
    if "visual content cannot be extracted as text" in lowered:
        return ""
    return text


def _is_retryable_staged_error(exc: Exception) -> bool:
    message = (str(exc) or "").strip().lower()
    if not message:
        return True
    return not any(marker in message for marker in NON_RETRYABLE_STAGED_ERRORS)


def _max_outbox_retries() -> int:
    try:
        return max(1, int(getattr(settings, "staged_file_processing_outbox_max_retries", 25) or 25))
    except Exception:
        return 25


def _coerce_redaction_list(raw_value: Any) -> List[str]:
    if not isinstance(raw_value, list):
        return []
    return [str(item).strip() for item in raw_value if isinstance(item, str) and str(item).strip()]


def _process_staged_file(staged_row: StagedFile, payload: Dict[str, Any]) -> Dict[str, Any]:
    blob_data = blob_storage_service.get_bytes(staged_row.filename)
    if not blob_data:
        raise ValueError("Failed to load file bytes from blob storage")

    extracted = _run_async_sync(
        FileProcessor.extract_text(
            blob_data,
            staged_row.file_type,
            staged_row.original_filename or "document",
        )
    )
    extracted_text = _normalize_extracted_text(extracted)
    redact_requested = bool(payload.get("redact") or getattr(staged_row, "redaction_requested", False))
    if redact_requested and staged_row.file_type not in IMAGE_EXTENSIONS and extracted_text:
        redaction_result = _run_async_sync(
            redact_text(
                extracted_text,
                user_redaction_list=_coerce_redaction_list(payload.get("user_redaction_list")),
            )
        )
        extracted_text = str(getattr(redaction_result, "text", extracted_text) or "")
        redaction_applied = bool(
            getattr(staged_row, "redaction_applied", False)
            or getattr(redaction_result, "redaction_performed", False)
        )
    else:
        redaction_applied = bool(getattr(staged_row, "redaction_applied", False))

    categories = list(getattr(staged_row, "redacted_categories_jsonb", []) or [])
    if redaction_applied and "user_redaction" not in categories:
        categories.append("user_redaction")

    return {
        "extracted_text": extracted_text,
        "redaction_applied": redaction_applied,
        "redacted_categories": categories,
    }


def process_staged_file_processing_outbox_batch_sync(
    db: Session,
    *,
    batch_size: int,
) -> Dict[str, int]:
    normalized_batch_size = max(1, int(batch_size or 100))
    rows = (
        db.query(StagedFileProcessingOutbox)
        .filter(
            StagedFileProcessingOutbox.event_type == STAGED_FILE_PROCESS_EVENT_TYPE,
            StagedFileProcessingOutbox.processed_at.is_(None),
        )
        .order_by(StagedFileProcessingOutbox.created_at.asc(), StagedFileProcessingOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(normalized_batch_size)
        .all()
    )
    if not rows:
        return {"scanned": 0, "processed": 0, "errors": 0}

    processed_at = datetime.now(timezone.utc)
    max_retries = _max_outbox_retries()
    processed = 0
    errors = 0
    staged_by_id = {
        str(row.id): row
        for row in (
            db.query(StagedFile)
            .filter(StagedFile.id.in_([str(item.staged_file_id) for item in rows if getattr(item, "staged_file_id", None)]))
            .all()
        )
    }

    for row in rows:
        staged_row = staged_by_id.get(str(row.staged_file_id))
        payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}

        if int(row.event_version or 0) != STAGED_FILE_PROCESS_EVENT_VERSION:
            row.processed_at = processed_at
            row.error = (
                f"dead_lettered:unsupported_event_version:{row.event_version}:expected:{STAGED_FILE_PROCESS_EVENT_VERSION}"
            )[:512]
            if staged_row is not None:
                staged_row.processing_status = "failed"
                staged_row.processing_error = "Unsupported staged file processing event version"
            errors += 1
            continue

        retry_count = int(row.retry_count or 0)
        if retry_count >= max_retries:
            row.processed_at = processed_at
            row.error = f"dead_lettered:max_retries_exceeded:{retry_count}"[:512]
            if staged_row is not None:
                staged_row.processing_status = "failed"
                staged_row.processing_error = "Staged file processing exceeded max retries"
            errors += 1
            continue

        if staged_row is None:
            row.processed_at = processed_at
            row.error = "staged file missing"
            processed += 1
            continue

        if str(getattr(staged_row, "processing_status", "") or "").strip().lower() == "completed":
            row.processed_at = processed_at
            row.error = None
            processed += 1
            continue

        staged_row.processing_status = "processing"
        staged_row.processing_error = None
        db.flush()

        try:
            result = _process_staged_file(staged_row, payload)
            staged_row.extracted_text = result["extracted_text"]
            staged_row.processing_status = "completed"
            staged_row.processing_error = None
            staged_row.processed_at = processed_at
            staged_row.redaction_applied = bool(result["redaction_applied"])
            staged_row.redacted_categories_jsonb = list(result["redacted_categories"])
            row.processed_at = processed_at
            row.error = None
            processed += 1
            log_event(
                logger,
                "INFO",
                "staged.file_processing.completed",
                "final",
                staged_file_id=str(staged_row.id),
                user_id=str(staged_row.user_id),
            )
        except Exception as exc:
            updated_retry_count = retry_count + 1
            row.retry_count = updated_retry_count
            retryable = _is_retryable_staged_error(exc)
            message = str(exc)[:512] or "staged file processing failed"
            staged_row.processing_status = "pending" if retryable and updated_retry_count < max_retries else "failed"
            staged_row.processing_error = message
            if retryable and updated_retry_count < max_retries:
                row.error = message
            else:
                row.processed_at = processed_at
                row.error = (
                    f"dead_lettered:{'retryable_error' if retryable else 'non_retryable_error'}:{updated_retry_count}:{message}"
                )[:512]
            errors += 1
            log_event(
                logger,
                "ERROR",
                "staged.file_processing.failed",
                "error",
                staged_file_id=str(staged_row.id),
                user_id=str(staged_row.user_id),
                retry_count=updated_retry_count,
                exc_info=exc,
            )

    return {"scanned": len(rows), "processed": processed, "errors": errors}
