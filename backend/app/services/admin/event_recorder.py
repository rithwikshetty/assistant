"""Lean admin event recorder for the post-rewrite analytics model."""

from __future__ import annotations

import logging
from datetime import date
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Callable

import redis
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...config.settings import settings
from ...database.models import AdminUserRollup, AnalyticsOutbox, UserActivity, UserLoginDaily
from ...logging import log_event

logger = logging.getLogger(__name__)


class AdminEventRecorder:
    """
    Lean recorder for the current analytics model.

    Legacy AdminStats* fan-out has been removed. Runtime paths can still call
    `record_*` helpers without paying heavy write-amplification costs.
    """

    @staticmethod
    def _normalize_day(value: datetime) -> tuple[datetime, date]:
        observed_at = value
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        observed_at_utc = observed_at.astimezone(timezone.utc)
        return observed_at_utc, observed_at_utc.date()

    @staticmethod
    def _resolve_target_id(raw_target_id: Any | None = None) -> str:
        if raw_target_id is None:
            return str(uuid4())
        candidate = str(raw_target_id).strip()
        return candidate if candidate else str(uuid4())

    @staticmethod
    def _normalize_identifier(raw_value: Any | None = None) -> str | None:
        if raw_value is None:
            return None
        candidate = str(raw_value).strip()
        return candidate or None

    def _record_behavior_event(
        self,
        db: Session,
        *,
        user_id: str | None,
        activity_type: str,
        target_id: Any | None = None,
        conversation_id: Any | None = None,
        project_id: Any | None = None,
        task_id: Any | None = None,
        run_id: Any | None = None,
        metadata_jsonb: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        outbox_payload: dict[str, Any] | None = None,
    ) -> None:
        if not user_id:
            return

        normalized_activity_type = str(activity_type or "").strip().lower()
        if not normalized_activity_type:
            return

        resolved_target_id = self._resolve_target_id(target_id)
        normalized_conversation_id = self._normalize_identifier(conversation_id)
        normalized_project_id = self._normalize_identifier(project_id)
        normalized_task_id = self._normalize_identifier(task_id)
        normalized_run_id = self._normalize_identifier(run_id)
        normalized_metadata = dict(metadata_jsonb) if metadata_jsonb else None
        normalized_created_at = None
        if created_at is not None:
            normalized_created_at, _ = self._normalize_day(created_at)

        row = UserActivity(
            user_id=str(user_id),
            activity_type=normalized_activity_type,
            target_id=resolved_target_id,
            conversation_id=normalized_conversation_id,
            project_id=normalized_project_id,
            task_id=normalized_task_id,
            run_id=normalized_run_id,
            metadata_jsonb=normalized_metadata,
        )
        if normalized_created_at is not None:
            row.created_at = normalized_created_at
        db.add(row)

        payload = {
            "user_id": str(user_id),
            "activity_type": normalized_activity_type,
            "target_id": resolved_target_id,
        }
        if normalized_conversation_id is not None:
            payload["conversation_id"] = normalized_conversation_id
        if normalized_project_id is not None:
            payload["project_id"] = normalized_project_id
        if normalized_task_id is not None:
            payload["task_id"] = normalized_task_id
        if normalized_run_id is not None:
            payload["run_id"] = normalized_run_id
        if normalized_metadata is not None:
            payload["metadata"] = normalized_metadata
        if normalized_created_at is not None:
            payload["created_at"] = normalized_created_at.isoformat()
        if outbox_payload:
            payload.update(outbox_payload)
        db.add(
            AnalyticsOutbox(
                event_type="analytics.activity.recorded",
                event_version=1,
                entity_id=resolved_target_id,
                payload_jsonb=payload,
            )
        )
        self._dispatch_activity_outbox_worker()

    @staticmethod
    def _increment_user_conversation_count(db: Session, *, user_id: str) -> None:
        if not user_id:
            return
        normalized_user_id = str(user_id)
        insert_stmt = pg_insert(AdminUserRollup).values(
            user_id=normalized_user_id,
            conversation_count=1,
            assistant_turn_count=0,
            total_cost_usd=0,
        )
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[AdminUserRollup.user_id],
                set_={
                    "conversation_count": AdminUserRollup.conversation_count + 1,
                    "updated_at": func.now(),
                },
            )
        )

    @staticmethod
    def _dispatch_activity_outbox_worker() -> None:
        batch_size = max(1, int(getattr(settings, "analytics_activity_outbox_batch_size", 250) or 250))
        countdown_seconds = 2
        cooldown_seconds = max(
            0,
            int(getattr(settings, "analytics_activity_outbox_dispatch_cooldown_seconds", 2) or 2),
        )
        lock_key = "assist:analytics:activity_outbox:dispatch"
        lock_client = None
        lock_acquired = False
        if cooldown_seconds > 0:
            try:
                lock_client = redis.Redis.from_url(settings.redis_url)
                lock_acquired = bool(lock_client.set(lock_key, "1", nx=True, ex=cooldown_seconds))
                if not lock_acquired:
                    return
            except Exception as exc:
                # Keep request path resilient even when lock infra is unavailable.
                log_event(
                    logger,
                    "WARNING",
                    "analytics.activity.outbox_batch.dispatch_lock_unavailable",
                    "retry",
                    batch_size=batch_size,
                    cooldown_seconds=cooldown_seconds,
                    exc_info=exc,
                )

        try:
            from .tasks import process_activity_outbox_batch

            process_activity_outbox_batch.apply_async(kwargs={"batch_size": batch_size}, countdown=countdown_seconds)
        except Exception as exc:
            # Keep request path resilient even when workers/broker are unavailable.
            log_event(
                logger,
                "WARNING",
                "analytics.activity.outbox_batch.enqueue_failed",
                "retry",
                batch_size=batch_size,
                countdown_seconds=countdown_seconds,
                exc_info=exc,
            )
            if lock_client is not None and lock_acquired:
                try:
                    lock_client.delete(lock_key)
                except Exception:
                    pass
            return

    def record_user_login(
        self,
        db: Session,
        *,
        user_id: str,
        logged_at: datetime | None = None,
        **_: Any,
    ) -> None:
        if not user_id:
            return

        observed_at_utc, login_day = self._normalize_day(logged_at or datetime.now(timezone.utc))

        row = (
            db.query(UserLoginDaily)
            .filter(
                UserLoginDaily.user_id == str(user_id),
                UserLoginDaily.login_date == login_day,
            )
            .first()
        )
        if row is None:
            db.add(
                UserLoginDaily(
                    user_id=str(user_id),
                    login_date=login_day,
                    first_login_at=observed_at_utc,
                    last_login_at=observed_at_utc,
                )
            )
            return

        if observed_at_utc > row.last_login_at:
            row.last_login_at = observed_at_utc

    def record_share_imported(self, db: Session, user_id: str, share_id: Any | None = None, **_: Any) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="share_imported",
            target_id=share_id,
        )

    def record_share_created(self, db: Session, user_id: str, share_id: Any | None = None, **_: Any) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="share_created",
            target_id=share_id,
        )

    def record_branch_created(
        self,
        db: Session,
        user_id: str,
        conversation_id: Any | None = None,
        target_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="conversation_branched",
            target_id=conversation_id or target_id,
            conversation_id=conversation_id or target_id,
        )

    def record_compaction(
        self,
        db: Session,
        user_id: str,
        conversation_id: Any | None = None,
        target_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="conversation_compacted",
            target_id=conversation_id or target_id,
            conversation_id=conversation_id or target_id,
        )

    def record_project_created(
        self,
        db: Session,
        user_id: str,
        project_id: Any | None = None,
        target_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="project_created",
            target_id=project_id or target_id,
            project_id=project_id or target_id,
        )

    def record_member_joined(
        self,
        db: Session,
        user_id: str,
        project_id: Any | None = None,
        target_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="group_joined",
            target_id=project_id or target_id,
            project_id=project_id or target_id,
        )

    def record_redaction_applied(
        self,
        db: Session,
        user_id: str,
        target_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="redaction_applied",
            target_id=target_id,
        )

    def record_redaction_entry_created(
        self,
        db: Session,
        user_id: str,
        target_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="redaction_entry_created",
            target_id=target_id,
        )

    def record_new_user(
        self,
        db: Session,
        user_id: str,
        **_: Any,
    ) -> None:
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="user_registered",
            target_id=user_id,
        )

    def record_new_conversation(
        self,
        db: Session,
        user_id: str,
        conversation_id: Any | None = None,
        **_: Any,
    ) -> None:
        self._increment_user_conversation_count(db, user_id=user_id)
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="conversation_created",
            target_id=conversation_id,
            conversation_id=conversation_id,
        )

    def record_file_upload(
        self,
        db: Session,
        user_id: str,
        target_id: Any | None = None,
        file_size_bytes: int | None = None,
        file_type: str | None = None,
        **_: Any,
    ) -> None:
        payload: dict[str, Any] = {}
        if file_size_bytes is not None:
            payload["file_size_bytes"] = int(file_size_bytes)
        if file_type:
            payload["file_type"] = str(file_type)
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="file_uploaded",
            target_id=target_id,
            metadata_jsonb=payload or None,
            outbox_payload=payload or None,
        )

    def record_user_message(
        self,
        db: Session,
        user_id: str,
        target_id: Any | None = None,
        message_id: Any | None = None,
        conversation_id: Any | None = None,
        run_id: Any | None = None,
        request_id: Any | None = None,
        created_at: datetime | None = None,
        **_: Any,
    ) -> None:
        resolved_message_id = message_id or target_id
        payload: dict[str, Any] = {}
        if resolved_message_id is not None:
            payload["message_id"] = str(resolved_message_id)
        if conversation_id is not None:
            payload["conversation_id"] = str(conversation_id)
        if run_id is not None:
            payload["run_id"] = str(run_id)
        if request_id is not None:
            payload["request_id"] = str(request_id)
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="user_message_submitted",
            target_id=resolved_message_id,
            conversation_id=conversation_id,
            run_id=run_id,
            metadata_jsonb={
                k: v
                for k, v in {
                    "message_id": payload.get("message_id"),
                    "request_id": payload.get("request_id"),
                }.items()
                if v is not None
            }
            or None,
            created_at=created_at,
            outbox_payload=payload or None,
        )

    def record_output_applied_to_live_work(
        self,
        db: Session,
        user_id: str,
        *,
        task_id: Any | None = None,
        conversation_id: Any | None = None,
        created_at: datetime | None = None,
        **_: Any,
    ) -> None:
        payload: dict[str, Any] = {}
        if conversation_id is not None:
            payload["conversation_id"] = str(conversation_id)
        if task_id is not None:
            payload["task_id"] = str(task_id)
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="output_applied_to_live_work",
            target_id=task_id,
            conversation_id=conversation_id,
            task_id=task_id,
            created_at=created_at,
            outbox_payload=payload or None,
        )

    def record_output_deployed_to_live_work(
        self,
        db: Session,
        user_id: str,
        *,
        task_id: Any | None = None,
        conversation_id: Any | None = None,
        created_at: datetime | None = None,
        **_: Any,
    ) -> None:
        payload: dict[str, Any] = {}
        if conversation_id is not None:
            payload["conversation_id"] = str(conversation_id)
        if task_id is not None:
            payload["task_id"] = str(task_id)
        self._record_behavior_event(
            db,
            user_id=user_id,
            activity_type="output_deployed_to_live_work",
            target_id=task_id,
            conversation_id=conversation_id,
            task_id=task_id,
            created_at=created_at,
            outbox_payload=payload or None,
        )

    def __getattr__(self, name: str) -> Callable[..., None]:
        if name.startswith("record_"):
            return self._noop
        raise AttributeError(name)

    @staticmethod
    def _noop(*_: Any, **__: Any) -> None:
        return None
