"""Project archive generation via durable outbox handled in-process."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ...config.database import SessionLocal
from ...config.settings import settings
from ...database.models import ProjectArchiveJob, ProjectArchiveOutbox
from ...logging import log_event
from .blob_storage_service import blob_storage_service
from .file_service import file_service

logger = logging.getLogger(__name__)

PROJECT_ARCHIVE_EVENT_TYPE = "project.archive.generate.requested"
PROJECT_ARCHIVE_EVENT_VERSION = 1
PROJECT_ARCHIVE_TASK_NAME = "app.project_archives.process_outbox_batch"
NON_RETRYABLE_ARCHIVE_ERRORS: tuple[str, ...] = (
    "no project knowledge files found",
    "no downloadable files are currently available",
)


def enqueue_project_archive_outbox_event(
    *,
    db: Session,
    archive_job_id: str,
    project_id: str,
    payload: Dict[str, Any] | None = None,
) -> ProjectArchiveOutbox:
    row = ProjectArchiveOutbox(
        event_type=PROJECT_ARCHIVE_EVENT_TYPE,
        event_version=PROJECT_ARCHIVE_EVENT_VERSION,
        archive_job_id=archive_job_id,
        project_id=project_id,
        payload_jsonb=payload or {},
    )
    db.add(row)
    return row


def dispatch_project_archive_outbox_worker(
    *,
    batch_size: int | None = None,
) -> None:
    resolved_batch_size = max(
        1,
        int(batch_size or getattr(settings, "project_archive_outbox_batch_size", 20) or 20),
    )
    db = SessionLocal()
    try:
        outcome = process_project_archive_outbox_batch_sync(
            db,
            batch_size=resolved_batch_size,
        )
        db.commit()
        log_event(
            logger,
            "INFO",
            "project.archive.outbox_batch.processed_inline",
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
            "project.archive.outbox_batch.inline_db_failed",
            "retry",
            task_name=PROJECT_ARCHIVE_TASK_NAME,
            batch_size=resolved_batch_size,
            exc_info=exc,
        )
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "WARNING",
            "project.archive.outbox_batch.inline_failed",
            "retry",
            task_name=PROJECT_ARCHIVE_TASK_NAME,
            batch_size=resolved_batch_size,
            exc_info=exc,
        )
    finally:
        db.close()


def _max_outbox_retries() -> int:
    try:
        return max(1, int(getattr(settings, "project_archive_outbox_max_retries", 25) or 25))
    except Exception:
        return 25


def _is_retryable_archive_error(exc: Exception) -> bool:
    message = (str(exc) or "").strip().lower()
    if not message:
        return True
    return not any(marker in message for marker in NON_RETRYABLE_ARCHIVE_ERRORS)


def _archive_storage_key(job: ProjectArchiveJob) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"archives/projects/{job.project_id}/{job.id}/{timestamp}.zip"


def process_project_archive_outbox_batch_sync(
    db: Session,
    *,
    batch_size: int,
) -> Dict[str, int]:
    normalized_batch_size = max(1, int(batch_size or 20))
    rows = (
        db.query(ProjectArchiveOutbox)
        .filter(
            ProjectArchiveOutbox.event_type == PROJECT_ARCHIVE_EVENT_TYPE,
            ProjectArchiveOutbox.processed_at.is_(None),
        )
        .order_by(ProjectArchiveOutbox.created_at.asc(), ProjectArchiveOutbox.id.asc())
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
    jobs_by_id = {
        str(job.id): job
        for job in (
            db.query(ProjectArchiveJob)
            .filter(ProjectArchiveJob.id.in_([str(row.archive_job_id) for row in rows if getattr(row, "archive_job_id", None)]))
            .all()
        )
    }

    for row in rows:
        job = jobs_by_id.get(str(row.archive_job_id))
        if int(row.event_version or 0) != PROJECT_ARCHIVE_EVENT_VERSION:
            row.processed_at = processed_at
            row.error = (
                f"dead_lettered:unsupported_event_version:{row.event_version}:expected:{PROJECT_ARCHIVE_EVENT_VERSION}"
            )[:512]
            if job is not None:
                job.status = "failed"
                job.error = "Unsupported archive generation event version"
            errors += 1
            continue

        retry_count = int(row.retry_count or 0)
        if retry_count >= max_retries:
            row.processed_at = processed_at
            row.error = f"dead_lettered:max_retries_exceeded:{retry_count}"[:512]
            if job is not None:
                job.status = "failed"
                job.error = "Archive generation exceeded max retries"
            errors += 1
            continue

        if job is None:
            row.processed_at = processed_at
            row.error = "archive job missing"
            processed += 1
            continue

        if str(job.status or "").strip().lower() == "completed" and job.storage_key:
            row.processed_at = processed_at
            row.error = None
            processed += 1
            continue

        job.status = "processing"
        job.error = None
        db.flush()

        archive_file = None
        try:
            archive_payload = file_service.build_project_files_archive(str(job.project_id), db)
            archive_file = archive_payload["archive_file"]
            storage_key = _archive_storage_key(job)
            blob_url = blob_storage_service.upload_fileobj_sync(storage_key, archive_file)
            job.status = "completed"
            job.total_files = int(archive_payload.get("total") or 0)
            job.included_files = int(archive_payload.get("included") or 0)
            job.skipped_files = int(archive_payload.get("skipped") or 0)
            job.archive_filename = str(archive_payload.get("archive_name") or "project-knowledge.zip")
            job.storage_key = storage_key
            job.blob_url = blob_url
            job.error = None
            job.completed_at = processed_at
            job.expires_at = processed_at + timedelta(days=7)
            row.processed_at = processed_at
            row.error = None
            processed += 1
            log_event(
                logger,
                "INFO",
                "project.archive.completed",
                "final",
                archive_job_id=str(job.id),
                project_id=str(job.project_id),
                included_files=job.included_files,
                skipped_files=job.skipped_files,
            )
        except Exception as exc:
            retryable = _is_retryable_archive_error(exc)
            updated_retry_count = retry_count + 1
            row.retry_count = updated_retry_count
            message = str(exc)[:512] or "project archive generation failed"
            job.status = "pending" if retryable and updated_retry_count < max_retries else "failed"
            job.error = message
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
                "project.archive.failed",
                "error",
                archive_job_id=str(job.id),
                project_id=str(job.project_id),
                retry_count=updated_retry_count,
                exc_info=exc,
            )
        finally:
            if archive_file is not None:
                archive_file.close()

    return {"scanned": len(rows), "processed": processed, "errors": errors}
