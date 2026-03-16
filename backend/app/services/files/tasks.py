"""Celery tasks for file-processing outbox workers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import OperationalError

from ...celery_app import celery_app
from ...config.database import SessionLocal
from ...logging import log_event
from .project_archive_service import process_project_archive_outbox_batch_sync
from .project_indexing_service import process_project_file_index_outbox_batch_sync
from .staged_processing_service import process_staged_file_processing_outbox_batch_sync

logger = logging.getLogger(__name__)


def _normalize_positive_int(raw_value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


@celery_app.task(
    name="app.project_files.process_index_outbox_batch",
    bind=True,
    autoretry_for=(),
    retry_backoff=False,
    max_retries=2,
)
def process_project_file_index_outbox_batch(self, *, batch_size: int = 100) -> None:
    """Process project knowledge indexing outbox events."""
    normalized_batch_size = _normalize_positive_int(batch_size, default=100, minimum=1)

    db = SessionLocal()
    try:
        outcome = process_project_file_index_outbox_batch_sync(
            db,
            batch_size=normalized_batch_size,
        )
        db.commit()
        log_event(
            logger,
            "INFO",
            "project.file_index.outbox_batch.processed",
            "final",
            batch_size=normalized_batch_size,
            scanned=int(outcome.get("scanned", 0)),
            processed=int(outcome.get("processed", 0)),
            errors=int(outcome.get("errors", 0)),
        )
    except OperationalError as exc:
        db.rollback()
        retry_count = int(getattr(self.request, "retries", 0)) + 1
        max_retries = int(getattr(self, "max_retries", 2) or 2)
        if retry_count <= max_retries:
            log_event(
                logger,
                "WARNING",
                "project.file_index.outbox_batch.retry_db_error",
                "retry",
                batch_size=normalized_batch_size,
                retry_count=retry_count,
                max_retries=max_retries,
                exc_info=exc,
            )
            raise self.retry(exc=exc, countdown=5)

        log_event(
            logger,
            "ERROR",
            "project.file_index.outbox_batch.failed",
            "error",
            batch_size=normalized_batch_size,
            retry_count=retry_count,
            max_retries=max_retries,
            exc_info=exc,
        )
        raise
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "ERROR",
            "project.file_index.outbox_batch.failed",
            "error",
            batch_size=normalized_batch_size,
            retry_count=int(getattr(self.request, "retries", 0)),
            max_retries=int(getattr(self, "max_retries", 2) or 2),
            exc_info=exc,
        )
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.staged_files.process_outbox_batch",
    bind=True,
    autoretry_for=(),
    retry_backoff=False,
    max_retries=2,
)
def process_staged_file_processing_outbox_batch(self, *, batch_size: int = 100) -> None:
    normalized_batch_size = _normalize_positive_int(batch_size, default=100, minimum=1)

    db = SessionLocal()
    try:
        outcome = process_staged_file_processing_outbox_batch_sync(
            db,
            batch_size=normalized_batch_size,
        )
        db.commit()
        log_event(
            logger,
            "INFO",
            "staged.file_processing.outbox_batch.processed",
            "final",
            batch_size=normalized_batch_size,
            scanned=int(outcome.get("scanned", 0)),
            processed=int(outcome.get("processed", 0)),
            errors=int(outcome.get("errors", 0)),
        )
    except OperationalError as exc:
        db.rollback()
        retry_count = int(getattr(self.request, "retries", 0)) + 1
        max_retries = int(getattr(self, "max_retries", 2) or 2)
        if retry_count <= max_retries:
            log_event(
                logger,
                "WARNING",
                "staged.file_processing.outbox_batch.retry_db_error",
                "retry",
                batch_size=normalized_batch_size,
                retry_count=retry_count,
                max_retries=max_retries,
                exc_info=exc,
            )
            raise self.retry(exc=exc, countdown=5)
        log_event(
            logger,
            "ERROR",
            "staged.file_processing.outbox_batch.failed",
            "error",
            batch_size=normalized_batch_size,
            retry_count=retry_count,
            max_retries=max_retries,
            exc_info=exc,
        )
        raise
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "ERROR",
            "staged.file_processing.outbox_batch.failed",
            "error",
            batch_size=normalized_batch_size,
            retry_count=int(getattr(self.request, "retries", 0)),
            max_retries=int(getattr(self, "max_retries", 2) or 2),
            exc_info=exc,
        )
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.project_archives.process_outbox_batch",
    bind=True,
    autoretry_for=(),
    retry_backoff=False,
    max_retries=2,
)
def process_project_archive_outbox_batch(self, *, batch_size: int = 20) -> None:
    normalized_batch_size = _normalize_positive_int(batch_size, default=20, minimum=1)

    db = SessionLocal()
    try:
        outcome = process_project_archive_outbox_batch_sync(
            db,
            batch_size=normalized_batch_size,
        )
        db.commit()
        log_event(
            logger,
            "INFO",
            "project.archive.outbox_batch.processed",
            "final",
            batch_size=normalized_batch_size,
            scanned=int(outcome.get("scanned", 0)),
            processed=int(outcome.get("processed", 0)),
            errors=int(outcome.get("errors", 0)),
        )
    except OperationalError as exc:
        db.rollback()
        retry_count = int(getattr(self.request, "retries", 0)) + 1
        max_retries = int(getattr(self, "max_retries", 2) or 2)
        if retry_count <= max_retries:
            log_event(
                logger,
                "WARNING",
                "project.archive.outbox_batch.retry_db_error",
                "retry",
                batch_size=normalized_batch_size,
                retry_count=retry_count,
                max_retries=max_retries,
                exc_info=exc,
            )
            raise self.retry(exc=exc, countdown=5)
        log_event(
            logger,
            "ERROR",
            "project.archive.outbox_batch.failed",
            "error",
            batch_size=normalized_batch_size,
            retry_count=retry_count,
            max_retries=max_retries,
            exc_info=exc,
        )
        raise
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "ERROR",
            "project.archive.outbox_batch.failed",
            "error",
            batch_size=normalized_batch_size,
            retry_count=int(getattr(self.request, "retries", 0)),
            max_retries=int(getattr(self, "max_retries", 2) or 2),
            exc_info=exc,
        )
        raise
    finally:
        db.close()
