"""Celery tasks for admin analytics."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from typing import Any, Dict

import redis
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ...celery_app import celery_app
from ...chat.services.assistant_turn_analytics import AssistantTurnAnalyticsService
from ...config.database import AsyncSessionLocal
from ...config.settings import settings
from ...database.models import AggActivityDay, AnalyticsOutbox, ChatRun, Conversation, Message, User
from ...logging import log_event
from ...utils.roles import is_admin_role
from .model_usage_analytics import ModelUsageAnalyticsService
from .model_usage_recorder import MODEL_USAGE_OUTBOX_EVENT
from .sector_classification_service import classify_and_upsert_sector

logger = logging.getLogger(__name__)
_ACTIVITY_OUTBOX_EVENT = "analytics.activity.recorded"
_ASSISTANT_TURN_OUTBOX_EVENT = "assistant.turn.finalized"


def _to_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_event_created_at(raw_value: Any, *, fallback: datetime | None) -> datetime:
    if isinstance(raw_value, datetime):
        return _to_utc(raw_value)
    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if candidate:
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                return _to_utc(parsed)
            except ValueError:
                pass
    return _to_utc(fallback)


class _InvalidUserIdError(ValueError):
    """Raised when an outbox row contains a non-UUID user_id."""


def _is_valid_uuid(raw_value: str) -> bool:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return False
    try:
        UUID(candidate)
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _partition_lookupable_user_ids(user_ids: set[str]) -> tuple[set[str], set[str]]:
    return _partition_lookupable_uuids(user_ids)


def _partition_lookupable_uuids(raw_ids: set[str]) -> tuple[set[str], set[str]]:
    valid: set[str] = set()
    invalid: set[str] = set()
    for raw_id in raw_ids:
        candidate = str(raw_id or "").strip()
        if not candidate:
            continue
        if _is_valid_uuid(candidate):
            valid.add(candidate)
        else:
            invalid.add(candidate)
    return valid, invalid


def _upsert_activity_day_row(
    db: Session,
    *,
    metric_date,
    scope: str,
    activity_type: str,
) -> None:
    insert_stmt = pg_insert(AggActivityDay).values(
        metric_date=metric_date,
        scope=scope,
        activity_type=activity_type,
        event_count=1,
    )
    db.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[
                AggActivityDay.metric_date,
                AggActivityDay.scope,
                AggActivityDay.activity_type,
            ],
            set_={
                "event_count": AggActivityDay.event_count + 1,
                "updated_at": func.now(),
            },
        )
    )


def _max_outbox_retries() -> int:
    try:
        return max(1, int(getattr(settings, "analytics_outbox_max_retries", 25) or 25))
    except Exception:
        return 25


def _mark_outbox_dead_letter(
    *,
    row: AnalyticsOutbox,
    processed_at: datetime,
    reason: str,
) -> None:
    row.processed_at = processed_at
    normalized_reason = str(reason or "").strip() or "max_retries_exceeded"
    row.error = f"dead_lettered:{normalized_reason}"[:512]


def _process_activity_outbox_batch_sync(db: Session, *, batch_size: int) -> Dict[str, int]:
    rows = (
        db.query(AnalyticsOutbox)
        .filter(
            AnalyticsOutbox.event_type == _ACTIVITY_OUTBOX_EVENT,
            AnalyticsOutbox.processed_at.is_(None),
        )
        .order_by(AnalyticsOutbox.created_at.asc(), AnalyticsOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, int(batch_size or 1)))
        .all()
    )
    if not rows:
        return {"scanned": 0, "processed": 0, "errors": 0}

    user_ids: set[str] = set()
    for row in rows:
        payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}
        raw_user_id = payload.get("user_id")
        user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
        if user_id:
            user_ids.add(user_id)

    lookupable_user_ids, invalid_user_ids = _partition_lookupable_user_ids(user_ids)
    if invalid_user_ids:
        log_event(
            logger,
            "WARNING",
            "analytics.activity.outbox.invalid_user_ids_detected",
            "retry",
            count=len(invalid_user_ids),
        )

    role_by_user: dict[str, Any] = {}
    if lookupable_user_ids:
        for uid, role in db.query(User.id, User.role).filter(User.id.in_(tuple(lookupable_user_ids))).all():
            role_by_user[str(uid)] = role

    processed = 0
    errors = 0
    processed_at = datetime.now(timezone.utc)
    max_retries = _max_outbox_retries()

    for row in rows:
        retry_count = int(row.retry_count or 0)
        if retry_count >= max_retries:
            _mark_outbox_dead_letter(
                row=row,
                processed_at=processed_at,
                reason=f"max_retries_exceeded:{retry_count}",
            )
            errors += 1
            continue

        try:
            with db.begin_nested():
                payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}
                activity_type = str(payload.get("activity_type") or "").strip().lower()
                if not activity_type:
                    raise ValueError("missing activity_type")

                raw_user_id = payload.get("user_id")
                user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
                if user_id and user_id in invalid_user_ids:
                    raise _InvalidUserIdError(user_id)
                user_id = user_id or None

                created_at = _parse_event_created_at(payload.get("created_at"), fallback=row.created_at)
                metric_date = created_at.date()

                _upsert_activity_day_row(
                    db,
                    metric_date=metric_date,
                    scope="all",
                    activity_type=activity_type,
                )
                if user_id is not None and not is_admin_role(role_by_user.get(user_id)):
                    _upsert_activity_day_row(
                        db,
                        metric_date=metric_date,
                        scope="non_admin",
                        activity_type=activity_type,
                    )

                row.processed_at = processed_at
                row.error = None
            processed += 1
        except Exception as exc:
            updated_retry_count = int(row.retry_count or 0) + 1
            row.retry_count = updated_retry_count
            if isinstance(exc, _InvalidUserIdError):
                log_event(
                    logger,
                    "WARNING",
                    "analytics.activity.outbox.invalid_user_id_row",
                    "retry",
                    row_id=int(getattr(row, "id", 0) or 0),
                    event_type=str(getattr(row, "event_type", "") or ""),
                    entity_id=str(getattr(row, "entity_id", "") or ""),
                    retry_count=updated_retry_count,
                )
            if updated_retry_count >= max_retries:
                _mark_outbox_dead_letter(
                    row=row,
                    processed_at=processed_at,
                    reason=f"max_retries_exceeded:{updated_retry_count}:{str(exc)[:120]}",
                )
            else:
                row.error = str(exc)[:512]
            errors += 1

    db.flush()
    return {"scanned": len(rows), "processed": processed, "errors": errors}


def _process_assistant_turn_outbox_batch_sync(db: Session, *, batch_size: int) -> Dict[str, int]:
    rows = (
        db.query(AnalyticsOutbox)
        .filter(
            AnalyticsOutbox.event_type == _ASSISTANT_TURN_OUTBOX_EVENT,
            AnalyticsOutbox.processed_at.is_(None),
        )
        .order_by(AnalyticsOutbox.created_at.asc(), AnalyticsOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, int(batch_size or 1)))
        .all()
    )
    if not rows:
        return {"scanned": 0, "processed": 0, "errors": 0}

    analytics_service = AssistantTurnAnalyticsService()
    processed = 0
    errors = 0
    processed_at = datetime.now(timezone.utc)
    max_retries = _max_outbox_retries()
    payload_by_row_id: dict[str, dict[str, Any]] = {}
    message_by_id: dict[str, Message] = {}
    conversation_by_id: dict[str, Conversation] = {}
    run_by_id: dict[str, ChatRun] = {}

    message_ids: set[str] = set()
    conversation_ids: set[str] = set()
    explicit_run_ids: set[str] = set()
    for row in rows:
        payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}
        payload_by_row_id[str(row.id)] = payload
        message_id = str(payload.get("message_id") or "").strip()
        conversation_id = str(payload.get("conversation_id") or "").strip()
        run_id = str(payload.get("run_id") or "").strip()
        if message_id:
            message_ids.add(message_id)
        if conversation_id:
            conversation_ids.add(conversation_id)
        if run_id:
            explicit_run_ids.add(run_id)

    lookupable_message_ids, invalid_message_ids = _partition_lookupable_uuids(message_ids)
    lookupable_conversation_ids, invalid_conversation_ids = _partition_lookupable_uuids(conversation_ids)
    lookupable_explicit_run_ids, invalid_run_ids = _partition_lookupable_uuids(explicit_run_ids)
    lookupable_run_ids = set(lookupable_explicit_run_ids)

    if lookupable_message_ids:
        prefetched_messages = (
            db.query(Message)
            .filter(Message.id.in_(tuple(lookupable_message_ids)))
            .all()
        )
        message_by_id = {str(message.id): message for message in prefetched_messages}
        message_run_ids = {
            str(message.run_id)
            for message in prefetched_messages
            if getattr(message, "run_id", None)
        }
        lookupable_run_ids.update(message_run_ids)
    if lookupable_conversation_ids:
        prefetched_conversations = (
            db.query(Conversation)
            .filter(Conversation.id.in_(tuple(lookupable_conversation_ids)))
            .all()
        )
        conversation_by_id = {str(conversation.id): conversation for conversation in prefetched_conversations}
    if lookupable_run_ids:
        prefetched_runs = db.query(ChatRun).filter(ChatRun.id.in_(tuple(lookupable_run_ids))).all()
        run_by_id = {str(run.id): run for run in prefetched_runs}

    for row in rows:
        retry_count = int(row.retry_count or 0)
        if retry_count >= max_retries:
            _mark_outbox_dead_letter(
                row=row,
                processed_at=processed_at,
                reason=f"max_retries_exceeded:{retry_count}",
            )
            errors += 1
            continue

        try:
            with db.begin_nested():
                payload = payload_by_row_id.get(str(row.id), {})
                message_id = str(payload.get("message_id") or "").strip()
                conversation_id = str(payload.get("conversation_id") or "").strip()
                if not message_id:
                    raise ValueError("missing message_id")
                if not conversation_id:
                    raise ValueError("missing conversation_id")
                if message_id in invalid_message_ids:
                    raise ValueError("invalid message_id")
                if conversation_id in invalid_conversation_ids:
                    raise ValueError("invalid conversation_id")

                message = message_by_id.get(message_id)
                if message is None or str(getattr(message, "conversation_id", "")) != conversation_id:
                    raise ValueError("message not found")

                conversation = conversation_by_id.get(conversation_id)
                if conversation is None:
                    raise ValueError("conversation not found")

                run_id = str(payload.get("run_id") or "").strip()
                if run_id and run_id in invalid_run_ids:
                    raise ValueError("invalid run_id")
                run = run_by_id.get(run_id) if run_id else None
                if run is None and getattr(message, "run_id", None):
                    run = run_by_id.get(str(message.run_id))

                usage_payload = payload.get("usage")
                if not isinstance(usage_payload, dict):
                    usage_payload = {}

                analytics_service.sync_rollups(
                    db=db,
                    conversation=conversation,
                    message=message,
                    run=run,
                    usage_payload=usage_payload,
                )

                row.processed_at = processed_at
                row.error = None
            processed += 1
        except Exception as exc:
            updated_retry_count = int(row.retry_count or 0) + 1
            row.retry_count = updated_retry_count
            if updated_retry_count >= max_retries:
                _mark_outbox_dead_letter(
                    row=row,
                    processed_at=processed_at,
                    reason=f"max_retries_exceeded:{updated_retry_count}:{str(exc)[:120]}",
                )
            else:
                row.error = str(exc)[:512]
            errors += 1

    db.flush()
    return {"scanned": len(rows), "processed": processed, "errors": errors}


def _process_model_usage_outbox_batch_sync(db: Session, *, batch_size: int) -> Dict[str, int]:
    rows = (
        db.query(AnalyticsOutbox)
        .filter(
            AnalyticsOutbox.event_type == MODEL_USAGE_OUTBOX_EVENT,
            AnalyticsOutbox.processed_at.is_(None),
        )
        .order_by(AnalyticsOutbox.created_at.asc(), AnalyticsOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, int(batch_size or 1)))
        .all()
    )
    if not rows:
        return {"scanned": 0, "processed": 0, "errors": 0}

    user_ids: set[str] = set()
    for row in rows:
        payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}
        raw_user_id = payload.get("user_id")
        user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
        if user_id:
            user_ids.add(user_id)

    lookupable_user_ids, invalid_user_ids = _partition_lookupable_user_ids(user_ids)
    if invalid_user_ids:
        log_event(
            logger,
            "WARNING",
            "analytics.model_usage.outbox.invalid_user_ids_detected",
            "retry",
            count=len(invalid_user_ids),
        )

    role_by_user: dict[str, Any] = {}
    if lookupable_user_ids:
        for uid, role in db.query(User.id, User.role).filter(User.id.in_(tuple(lookupable_user_ids))).all():
            role_by_user[str(uid)] = role

    analytics_service = ModelUsageAnalyticsService()
    processed = 0
    errors = 0
    processed_at = datetime.now(timezone.utc)
    max_retries = _max_outbox_retries()

    for row in rows:
        retry_count = int(row.retry_count or 0)
        if retry_count >= max_retries:
            _mark_outbox_dead_letter(
                row=row,
                processed_at=processed_at,
                reason=f"max_retries_exceeded:{retry_count}",
            )
            errors += 1
            continue

        try:
            with db.begin_nested():
                payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}
                event_id = str(row.entity_id or payload.get("event_id") or "").strip()
                if not event_id:
                    raise ValueError("missing event_id")

                raw_user_id = payload.get("user_id")
                user_id = str(raw_user_id).strip() if raw_user_id is not None else ""
                if user_id and user_id in invalid_user_ids:
                    raise _InvalidUserIdError(user_id)
                is_admin_user = is_admin_role(role_by_user.get(user_id)) if user_id else None

                analytics_service.sync_rollups(
                    db=db,
                    event_id=event_id,
                    payload=payload,
                    is_admin_user=is_admin_user,
                    fallback_created_at=row.created_at,
                )

                row.processed_at = processed_at
                row.error = None
            processed += 1
        except Exception as exc:
            updated_retry_count = int(row.retry_count or 0) + 1
            row.retry_count = updated_retry_count
            if updated_retry_count >= max_retries:
                _mark_outbox_dead_letter(
                    row=row,
                    processed_at=processed_at,
                    reason=f"max_retries_exceeded:{updated_retry_count}:{str(exc)[:120]}",
                )
            else:
                row.error = str(exc)[:512]
            errors += 1

    db.flush()
    return {"scanned": len(rows), "processed": processed, "errors": errors}


def _cleanup_analytics_outbox_sync(
    db: Session,
    *,
    batch_size: int,
    retention_days: int,
) -> Dict[str, int]:
    safe_batch_size = max(1, int(batch_size or 1))
    safe_retention_days = max(1, int(retention_days or 1))
    cutoff = datetime.now(timezone.utc) - timedelta(days=safe_retention_days)

    candidate_ids = [
        int(row_id)
        for (row_id,) in (
            db.query(AnalyticsOutbox.id)
            .filter(
                AnalyticsOutbox.processed_at.isnot(None),
                AnalyticsOutbox.processed_at < cutoff,
            )
            .order_by(AnalyticsOutbox.processed_at.asc(), AnalyticsOutbox.id.asc())
            .limit(safe_batch_size)
            .all()
        )
    ]
    if not candidate_ids:
        return {"deleted": 0}

    deleted = (
        db.query(AnalyticsOutbox)
        .filter(AnalyticsOutbox.id.in_(tuple(candidate_ids)))
        .delete(synchronize_session=False)
    )
    db.flush()
    return {"deleted": int(deleted or 0)}


@celery_app.task(
    name="app.analytics.process_activity_outbox_batch",
    bind=True,
    ignore_result=True,
    acks_late=False,
)
def process_activity_outbox_batch(self, *, batch_size: int = 250) -> None:
    """Process analytics activity outbox events into agg_activity_day."""

    async def _run() -> Dict[str, int]:
        async with AsyncSessionLocal() as db:
            try:
                outcome = await db.run_sync(
                    lambda sync_db: _process_activity_outbox_batch_sync(
                        sync_db,
                        batch_size=batch_size,
                    )
                )
                await db.commit()
                return dict(outcome or {})
            except IntegrityError:
                await db.rollback()
                raise
            except OperationalError:
                await db.rollback()
                raise
            except Exception:
                await db.rollback()
                raise

    try:
        result = asyncio.run(_run())
        log_event(
            logger,
            "INFO",
            "analytics.activity.outbox_batch.processed",
            "timing",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            scanned=int(result.get("scanned", 0)),
            processed=int(result.get("processed", 0)),
            errors=int(result.get("errors", 0)),
        )
    except (OperationalError, IntegrityError) as exc:
        log_event(
            logger,
            "WARNING",
            "analytics.activity.outbox_batch.retry_db_error",
            "retry",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            exc_info=exc,
        )
        raise self.retry(exc=exc, countdown=3, max_retries=3)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "analytics.activity.outbox_batch.failed",
            "error",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            exc_info=exc,
        )
        raise


@celery_app.task(
    name="app.analytics.process_assistant_turn_outbox_batch",
    bind=True,
    ignore_result=True,
    acks_late=False,
)
def process_assistant_turn_outbox_batch(self, *, batch_size: int = 250) -> None:
    """Process assistant turn outbox events into analytics fact/aggregate tables."""

    async def _run() -> Dict[str, int]:
        async with AsyncSessionLocal() as db:
            try:
                outcome = await db.run_sync(
                    lambda sync_db: _process_assistant_turn_outbox_batch_sync(
                        sync_db,
                        batch_size=batch_size,
                    )
                )
                await db.commit()
                return dict(outcome or {})
            except IntegrityError:
                await db.rollback()
                raise
            except OperationalError:
                await db.rollback()
                raise
            except Exception:
                await db.rollback()
                raise

    try:
        result = asyncio.run(_run())
        log_event(
            logger,
            "INFO",
            "analytics.assistant_turn.outbox_batch.processed",
            "timing",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            scanned=int(result.get("scanned", 0)),
            processed=int(result.get("processed", 0)),
            errors=int(result.get("errors", 0)),
        )
    except (OperationalError, IntegrityError) as exc:
        log_event(
            logger,
            "WARNING",
            "analytics.assistant_turn.outbox_batch.retry_db_error",
            "retry",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            exc_info=exc,
        )
        raise self.retry(exc=exc, countdown=3, max_retries=3)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "analytics.assistant_turn.outbox_batch.failed",
            "error",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            exc_info=exc,
        )
        raise


@celery_app.task(
    name="app.analytics.process_model_usage_outbox_batch",
    bind=True,
    ignore_result=True,
    acks_late=False,
)
def process_model_usage_outbox_batch(self, *, batch_size: int = 250) -> None:
    """Process non-chat model usage outbox events into fact/aggregate tables."""

    async def _run() -> Dict[str, int]:
        async with AsyncSessionLocal() as db:
            try:
                outcome = await db.run_sync(
                    lambda sync_db: _process_model_usage_outbox_batch_sync(
                        sync_db,
                        batch_size=batch_size,
                    )
                )
                await db.commit()
                return dict(outcome or {})
            except IntegrityError:
                await db.rollback()
                raise
            except OperationalError:
                await db.rollback()
                raise
            except Exception:
                await db.rollback()
                raise

    try:
        result = asyncio.run(_run())
        log_event(
            logger,
            "INFO",
            "analytics.model_usage.outbox_batch.processed",
            "timing",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            scanned=int(result.get("scanned", 0)),
            processed=int(result.get("processed", 0)),
            errors=int(result.get("errors", 0)),
        )
    except (OperationalError, IntegrityError) as exc:
        log_event(
            logger,
            "WARNING",
            "analytics.model_usage.outbox_batch.retry_db_error",
            "retry",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            exc_info=exc,
        )
        raise self.retry(exc=exc, countdown=3, max_retries=3)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "analytics.model_usage.outbox_batch.failed",
            "error",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            exc_info=exc,
        )
        raise


@celery_app.task(
    name="app.analytics.cleanup_analytics_outbox",
    bind=True,
    ignore_result=True,
    acks_late=False,
)
def cleanup_analytics_outbox(
    self,
    *,
    batch_size: int = 1000,
    retention_days: int = 14,
) -> None:
    """Delete processed outbox rows older than the configured retention window."""

    async def _run() -> Dict[str, int]:
        async with AsyncSessionLocal() as db:
            try:
                outcome = await db.run_sync(
                    lambda sync_db: _cleanup_analytics_outbox_sync(
                        sync_db,
                        batch_size=batch_size,
                        retention_days=retention_days,
                    )
                )
                await db.commit()
                return dict(outcome or {})
            except IntegrityError:
                await db.rollback()
                raise
            except OperationalError:
                await db.rollback()
                raise
            except Exception:
                await db.rollback()
                raise

    try:
        result = asyncio.run(_run())
        log_event(
            logger,
            "INFO",
            "analytics.outbox.cleanup.processed",
            "timing",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            retention_days=retention_days,
            deleted=int(result.get("deleted", 0)),
        )
    except (OperationalError, IntegrityError) as exc:
        log_event(
            logger,
            "WARNING",
            "analytics.outbox.cleanup.retry_db_error",
            "retry",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            retention_days=retention_days,
            exc_info=exc,
        )
        raise self.retry(exc=exc, countdown=3, max_retries=3)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "analytics.outbox.cleanup.failed",
            "error",
            task_id=getattr(getattr(self, "request", None), "id", None),
            batch_size=batch_size,
            retention_days=retention_days,
            exc_info=exc,
        )
        raise


@celery_app.task(
    name="app.analytics.classify_conversation_sector",
    bind=True,
    ignore_result=True,
    acks_late=False,
)
def classify_conversation_sector(self, *, conversation_id: str) -> None:
    """Classify a conversation into a sector for admin analytics."""
    lock_client: redis.Redis | None = None
    lock_key = f"assist:sector_classification:lock:{conversation_id}"
    lock_token = uuid4().hex
    lock_acquired = False

    try:
        try:
            lock_client = redis.Redis.from_url(settings.redis_url)
            lock_acquired = bool(lock_client.set(lock_key, lock_token, nx=True, ex=180))
            if not lock_acquired:
                log_event(
                    logger,
                    "INFO",
                    "sector.classify.skipped_locked",
                    "timing",
                    conversation_id=conversation_id,
                    task_id=getattr(getattr(self, "request", None), "id", None),
                )
                return
        except Exception as lock_exc:
            # Keep classification resilient even if Redis locking is unavailable.
            lock_client = None
            lock_acquired = False
            log_event(
                logger,
                "WARNING",
                "sector.classify.lock_unavailable",
                "retry",
                conversation_id=conversation_id,
                task_id=getattr(getattr(self, "request", None), "id", None),
                exc_info=lock_exc,
            )

        async def _run() -> Dict[str, Any]:
            async with AsyncSessionLocal() as db:
                try:
                    outcome = await db.run_sync(
                        lambda sync_db: classify_and_upsert_sector(sync_db, conversation_id)
                    )
                    await db.commit()
                    return dict(outcome or {})
                except IntegrityError:
                    await db.rollback()
                    raise
                except OperationalError:
                    await db.rollback()
                    raise
                except Exception:
                    await db.rollback()
                    raise

        result = asyncio.run(_run())
        status = str(result.get("status") or "unknown")
        level = "INFO" if status == "classified" else "DEBUG"
        event_name = (
            "sector.classify.completed"
            if status == "classified"
            else "sector.classify.skipped"
        )
        log_event(
            logger,
            level,
            event_name,
            "timing",
            conversation_id=conversation_id,
            task_id=getattr(getattr(self, "request", None), "id", None),
            **result,
        )
    except (OperationalError, IntegrityError) as exc:
        log_event(
            logger,
            "WARNING",
            "sector.classify.retry_db_error",
            "retry",
            conversation_id=conversation_id,
            task_id=getattr(getattr(self, "request", None), "id", None),
            exc_info=exc,
        )
        raise self.retry(exc=exc, countdown=3, max_retries=3)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "sector.classify.failed",
            "error",
            conversation_id=conversation_id,
            task_id=getattr(getattr(self, "request", None), "id", None),
            exc_info=exc,
        )
        raise
    finally:
        if lock_client is not None and lock_acquired:
            release_script = (
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('del', KEYS[1]) "
                "else return 0 end"
            )
            try:
                lock_client.eval(release_script, 1, lock_key, lock_token)
            except Exception:
                log_event(
                    logger,
                    "DEBUG",
                    "sector.classify.lock_release_failed",
                    "retry",
                    conversation_id=conversation_id,
                )
