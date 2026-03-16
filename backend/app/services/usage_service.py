from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import Date, cast, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config.settings import settings
from ..database.models import (
    AdminGlobalSnapshot,
    AggModelDay,
    AggModelUsageDay,
    AggUsageDay,
    Conversation,
    FactAssistantTurn,
    File,
    User,
    UserLoginDaily,
)
from .model_buckets import normalize_runtime_bucket, sort_bucket_key
from ..utils.roles import non_admin_role_filter
from ..utils.timezone_context import DEFAULT_REPORTING_TIMEZONE


def _to_float(value: Any, digits: int = 6) -> float:
    if value is None:
        return 0.0
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


_PROCESS_LABEL_OVERRIDES: Dict[str, str] = {
    "chat": "Chat",
    "title_generation": "Title generation",
    "suggestion_generation": "Suggestion generation",
    "code_execution_retry_fix": "Code execution retry fix",
    "retrieval_spons_synthesis": "Spon's retrieval synthesis",
    "project_index_embeddings_batch": "Project indexing embeddings",
    "project_search_query_embedding": "Project search embedding",
    "voice_transcription": "Voice transcription",
    "sector_classification": "Sector classification",
    "unknown_operation": "Unknown operation",
}


def _format_process_label(raw_process: Any) -> str:
    normalized = str(raw_process or "").strip().lower()
    if not normalized:
        return "Unknown operation"
    if normalized in _PROCESS_LABEL_OVERRIDES:
        return _PROCESS_LABEL_OVERRIDES[normalized]
    return normalized.replace("_", " ").strip().title() or "Unknown operation"


def _sort_model_usage_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            -int(row.get("message_count") or 0),
            sort_bucket_key(str(row.get("model", ""))),
        )
    )
    return rows


def _date_range(start_day: date, end_day: date) -> List[date]:
    if end_day < start_day:
        return []
    span = (end_day - start_day).days
    return [start_day + timedelta(days=i) for i in range(span + 1)]


@dataclass(frozen=True)
class UsageWindow:
    range_start_dt: datetime
    range_end_dt: datetime
    range_start_day: date
    range_end_day: date
    series_start_day: date
    ensure_start_day: date
    day_sequence: List[date]


def _build_window(
    *,
    now: datetime,
    days: int,
    start_date: Optional[date],
    end_date: Optional[date],
) -> UsageWindow:
    if start_date and end_date:
        start_day = min(start_date, end_date)
        end_day = max(start_date, end_date)
    else:
        safe_days = max(1, int(days or 1))
        end_day = now.date()
        start_day = end_day - timedelta(days=safe_days - 1)
    range_start_dt = datetime.combine(start_day, datetime.min.time(), timezone.utc)
    range_end_dt = datetime.combine(end_day, datetime.max.time(), timezone.utc)
    series_days = max(1, min((end_day - start_day).days + 1, 90))
    series_start_day = end_day - timedelta(days=series_days - 1)
    return UsageWindow(
        range_start_dt=range_start_dt,
        range_end_dt=range_end_dt,
        range_start_day=start_day,
        range_end_day=end_day,
        series_start_day=series_start_day,
        ensure_start_day=start_day,
        day_sequence=_date_range(series_start_day, end_day),
    )


def _build_usage_window(
    *,
    now: datetime,
    days: int,
    start_date: Optional[date],
    end_date: Optional[date],
) -> UsageWindow:
    """Build a usage window with the service's day-range semantics."""
    if start_date and end_date:
        range_start_day = min(start_date, end_date)
        range_end_day = max(start_date, end_date)
        series_start_day = range_start_day
    else:
        end_day = now.date()
        safe_days = max(1, int(days or 0))
        range_end_day = end_day
        range_start_day = end_day - timedelta(days=safe_days)
        if safe_days <= 1:
            series_start_day = end_day
        else:
            series_start_day = max(range_start_day, end_day - timedelta(days=89))

    range_start_dt = datetime.combine(range_start_day, datetime.min.time(), timezone.utc)
    range_end_dt = datetime.combine(range_end_day, datetime.max.time(), timezone.utc)
    return UsageWindow(
        range_start_dt=range_start_dt,
        range_end_dt=range_end_dt,
        range_start_day=range_start_day,
        range_end_day=range_end_day,
        series_start_day=series_start_day,
        ensure_start_day=range_start_day,
        day_sequence=_date_range(series_start_day, range_end_day),
    )


class UsageService:
    @staticmethod
    def _scope_users(query, *, include_admins: bool, user_model=User):
        return query if include_admins else query.filter(non_admin_role_filter(user_model.role))

    @staticmethod
    def _scope_label(include_admins: bool) -> str:
        return "all" if include_admins else "non_admin"

    @staticmethod
    def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _assistant_rollup_from_aggregate(
        self,
        *,
        db: Session,
        scope: str,
        start_day: Optional[date] = None,
        end_day: Optional[date] = None,
    ) -> Dict[str, Any]:
        query = (
            db.query(
                func.coalesce(func.sum(AggUsageDay.assistant_messages_count), 0).label("assistant_messages"),
                func.coalesce(func.sum(AggUsageDay.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(AggUsageDay.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(AggUsageDay.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(AggUsageDay.latency_sum_ms), 0).label("latency_sum_ms"),
                func.coalesce(func.sum(AggUsageDay.latency_samples), 0).label("latency_samples"),
                func.coalesce(func.sum(AggUsageDay.tool_call_count), 0).label("tool_call_count"),
                func.coalesce(func.sum(AggUsageDay.cost_usd), 0).label("cost_usd"),
            )
            .filter(AggUsageDay.scope == scope)
        )
        if start_day is not None:
            query = query.filter(AggUsageDay.metric_date >= start_day)
        if end_day is not None:
            query = query.filter(AggUsageDay.metric_date <= end_day)
        row = query.one()
        assistant_messages = int(row.assistant_messages or 0)
        input_tokens = int(row.input_tokens or 0)
        output_tokens = int(row.output_tokens or 0)
        total_tokens = int(row.total_tokens or 0)
        latency_sum = int(row.latency_sum_ms or 0)
        latency_samples = int(row.latency_samples or 0)
        tool_sum = int(row.tool_call_count or 0)
        cost_usd = Decimal(str(row.cost_usd or 0))
        return {
            "message_count": assistant_messages,
            "effective_input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "avg_response_latency_ms": (float(latency_sum) / float(latency_samples)) if latency_samples > 0 else None,
            "avg_tool_calls": (float(tool_sum) / float(assistant_messages)) if assistant_messages > 0 else None,
            "cost_usd": _to_float(cost_usd, digits=8),
        }

    def _messages_count_from_aggregate(
        self,
        *,
        db: Session,
        scope: str,
        start_day: Optional[date] = None,
        end_day: Optional[date] = None,
    ) -> int:
        query = db.query(func.coalesce(func.sum(AggUsageDay.messages_count), 0)).filter(AggUsageDay.scope == scope)
        if start_day is not None:
            query = query.filter(AggUsageDay.metric_date >= start_day)
        if end_day is not None:
            query = query.filter(AggUsageDay.metric_date <= end_day)
        return int(query.scalar() or 0)

    def _compute_global_totals(
        self,
        *,
        db: Session,
        include_admins: bool,
        include_file_totals: bool,
    ) -> Dict[str, int]:
        scope = self._scope_label(include_admins=include_admins)
        total_users = int(
            self._scope_users(db.query(func.count(User.id)), include_admins=include_admins).scalar() or 0
        )
        total_conversations = int(
            self._scope_users(
                db.query(func.count(Conversation.id)).join(User, User.id == Conversation.user_id),
                include_admins=include_admins,
            ).scalar()
            or 0
        )
        total_messages = self._messages_count_from_aggregate(db=db, scope=scope)
        total_files = 0
        total_storage_bytes = 0
        if include_file_totals:
            total_files = int(
                self._scope_users(
                    db.query(func.count(File.id)).join(User, User.id == File.user_id),
                    include_admins=include_admins,
                ).scalar()
                or 0
            )
            total_storage_bytes = int(
                self._scope_users(
                    db.query(func.coalesce(func.sum(File.file_size), 0)).join(User, User.id == File.user_id),
                    include_admins=include_admins,
                ).scalar()
                or 0
            )
        return {
            "total_users": total_users,
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "total_files": total_files,
            "total_storage_bytes": total_storage_bytes,
        }

    def _upsert_global_snapshot(
        self,
        *,
        db: Session,
        scope: str,
        totals: Dict[str, int],
        refreshed_at: datetime,
    ) -> None:
        insert_stmt = pg_insert(AdminGlobalSnapshot).values(
            scope=scope,
            total_users=max(0, int(totals.get("total_users", 0) or 0)),
            total_conversations=max(0, int(totals.get("total_conversations", 0) or 0)),
            total_messages=max(0, int(totals.get("total_messages", 0) or 0)),
            total_files=max(0, int(totals.get("total_files", 0) or 0)),
            total_storage_bytes=max(0, int(totals.get("total_storage_bytes", 0) or 0)),
            refreshed_at=refreshed_at,
        )
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[AdminGlobalSnapshot.scope],
                set_={
                    "total_users": insert_stmt.excluded.total_users,
                    "total_conversations": insert_stmt.excluded.total_conversations,
                    "total_messages": insert_stmt.excluded.total_messages,
                    "total_files": insert_stmt.excluded.total_files,
                    "total_storage_bytes": insert_stmt.excluded.total_storage_bytes,
                    "refreshed_at": insert_stmt.excluded.refreshed_at,
                    "updated_at": func.now(),
                },
            )
        )

    def _global_totals_from_snapshot(
        self,
        *,
        db: Session,
        include_admins: bool,
        include_file_totals: bool,
    ) -> Dict[str, int]:
        scope = self._scope_label(include_admins=include_admins)
        snapshot = db.query(AdminGlobalSnapshot).filter(AdminGlobalSnapshot.scope == scope).first()
        now_utc = datetime.now(timezone.utc)
        max_age_seconds = max(
            30,
            int(getattr(settings, "admin_global_snapshot_max_age_seconds", 300) or 300),
        )
        refreshed_at_utc = self._as_utc(getattr(snapshot, "refreshed_at", None))
        is_fresh = (
            refreshed_at_utc is not None
            and (now_utc - refreshed_at_utc) <= timedelta(seconds=max_age_seconds)
        )

        if snapshot is not None and is_fresh:
            return {
                "total_users": int(snapshot.total_users or 0),
                "total_conversations": int(snapshot.total_conversations or 0),
                "total_messages": int(snapshot.total_messages or 0),
                "total_files": int(snapshot.total_files or 0),
                "total_storage_bytes": int(snapshot.total_storage_bytes or 0),
            }

        computed = self._compute_global_totals(
            db=db,
            include_admins=include_admins,
            include_file_totals=include_file_totals,
        )
        if not include_file_totals and snapshot is not None:
            computed["total_files"] = int(snapshot.total_files or 0)
            computed["total_storage_bytes"] = int(snapshot.total_storage_bytes or 0)
        self._upsert_global_snapshot(
            db=db,
            scope=scope,
            totals=computed,
            refreshed_at=now_utc,
        )
        return computed

    def _daily_rows(
        self,
        *,
        db: Session,
        scope: str,
        start_day: date,
        end_day: date,
    ) -> Dict[date, AggUsageDay]:
        rows = (
            db.query(AggUsageDay)
            .filter(
                AggUsageDay.scope == scope,
                AggUsageDay.metric_date >= start_day,
                AggUsageDay.metric_date <= end_day,
            )
            .all()
        )
        return {row.metric_date: row for row in rows if row.metric_date is not None}

    def _created_users_by_day(
        self,
        *,
        db: Session,
        include_admins: bool,
        start_day: date,
        end_day: date,
    ) -> Dict[date, int]:
        rows = (
            self._scope_users(
                db.query(cast(User.created_at, Date).label("d"), func.count(User.id)),
                include_admins=include_admins,
            )
            .filter(User.created_at >= start_day, User.created_at < (end_day + timedelta(days=1)))
            .group_by("d")
            .all()
        )
        return {d: int(c or 0) for d, c in rows if isinstance(d, date)}

    def _created_conversations_by_day(
        self,
        *,
        db: Session,
        include_admins: bool,
        start_day: date,
        end_day: date,
    ) -> Dict[date, int]:
        rows = (
            self._scope_users(
                db.query(cast(Conversation.created_at, Date).label("d"), func.count(Conversation.id))
                .join(User, User.id == Conversation.user_id),
                include_admins=include_admins,
            )
            .filter(Conversation.created_at >= start_day, Conversation.created_at < (end_day + timedelta(days=1)))
            .group_by("d")
            .all()
        )
        return {d: int(c or 0) for d, c in rows if isinstance(d, date)}

    def _file_uploads_by_day(
        self,
        *,
        db: Session,
        include_admins: bool,
        start_day: date,
        end_day: date,
    ) -> Dict[date, int]:
        rows = (
            self._scope_users(
                db.query(cast(File.created_at, Date).label("d"), func.count(File.id))
                .join(User, User.id == File.user_id),
                include_admins=include_admins,
            )
            .filter(File.created_at >= start_day, File.created_at < (end_day + timedelta(days=1)))
            .group_by("d")
            .all()
        )
        return {d: int(c or 0) for d, c in rows if isinstance(d, date)}

    @staticmethod
    def _empty_assistant_rollup() -> Dict[str, Any]:
        return {
            "message_count": 0,
            "effective_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "avg_response_latency_ms": None,
            "avg_tool_calls": None,
            "cost_usd": 0.0,
        }

    def get_summary(
        self,
        db: Session,
        days: int = 30,
        include_admins: bool = False,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_extended: bool = True,
        include_global_totals: bool = True,
        include_lifetime_rollups: bool = True,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        window = _build_window(now=now, days=days, start_date=start_date, end_date=end_date)
        scope = self._scope_label(include_admins=include_admins)

        if include_global_totals:
            global_totals = self._global_totals_from_snapshot(
                db=db,
                include_admins=include_admins,
                include_file_totals=include_extended,
            )
            total_users = int(global_totals.get("total_users", 0) or 0)
            total_conversations = int(global_totals.get("total_conversations", 0) or 0)
            total_messages = int(global_totals.get("total_messages", 0) or 0)
            total_files = int(global_totals.get("total_files", 0) or 0) if include_extended else 0
            total_storage_bytes = (
                int(global_totals.get("total_storage_bytes", 0) or 0)
                if include_extended
                else 0
            )
        else:
            total_users = 0
            total_conversations = 0
            total_messages = 0
            total_files = 0
            total_storage_bytes = 0

        daily_by_day = self._daily_rows(
            db=db,
            scope=scope,
            start_day=window.series_start_day,
            end_day=window.range_end_day,
        )
        conversations_created_by_day = self._created_conversations_by_day(
            db=db,
            include_admins=include_admins,
            start_day=window.series_start_day,
            end_day=window.range_end_day,
        )
        users_created_by_day: Dict[date, int] = {}
        file_uploads_by_day: Dict[date, int] = {}
        if include_extended:
            users_created_by_day = self._created_users_by_day(
                db=db,
                include_admins=include_admins,
                start_day=window.series_start_day,
                end_day=window.range_end_day,
            )
            file_uploads_by_day = self._file_uploads_by_day(
                db=db,
                include_admins=include_admins,
                start_day=window.series_start_day,
                end_day=window.range_end_day,
            )

        users_per_day: List[Dict[str, Any]] = []
        conversations_per_day: List[Dict[str, Any]] = []
        messages_per_day: List[Dict[str, Any]] = []
        file_uploads_per_day: List[Dict[str, Any]] = []
        active_users_per_day: List[Dict[str, Any]] = []

        for day in window.day_sequence:
            row = daily_by_day.get(day)
            total_day_messages = int(row.messages_count or 0) if row else 0
            assistant_day_messages = int(row.assistant_messages_count or 0) if row else 0
            user_day_messages = max(0, total_day_messages - assistant_day_messages)

            date_label = day.strftime("%Y-%m-%d")
            users_per_day.append({"date": date_label, "count": int(users_created_by_day.get(day, 0))})
            conversations_per_day.append({"date": date_label, "count": int(conversations_created_by_day.get(day, 0))})
            messages_per_day.append(
                {
                    "date": date_label,
                    "total": total_day_messages,
                    "user": user_day_messages,
                    "assistant": assistant_day_messages,
                }
            )
            file_uploads_per_day.append({"date": date_label, "count": int(file_uploads_by_day.get(day, 0))})
            active_users_per_day.append({"date": date_label, "count": int(row.active_users or 0) if row else 0})

        assistant_usage_range = self._assistant_rollup_from_aggregate(
            db=db,
            scope=scope,
            start_day=window.range_start_day,
            end_day=window.range_end_day,
        )
        assistant_usage_lifetime = (
            self._assistant_rollup_from_aggregate(
                db=db,
                scope=scope,
            )
            if include_lifetime_rollups
            else self._empty_assistant_rollup()
        )

        messages_last_n_days = self._messages_count_from_aggregate(
            db=db,
            scope=scope,
            start_day=window.range_start_day,
            end_day=window.range_end_day,
        )
        file_uploads_last_n_days = (
            int(
                self._scope_users(
                    db.query(func.count(File.id)).join(User, User.id == File.user_id),
                    include_admins=include_admins,
                )
                .filter(
                    File.created_at >= window.range_start_dt,
                    File.created_at <= window.range_end_dt,
                )
                .scalar()
                or 0
            )
            if include_extended
            else 0
        )

        assistant_active_users = self._scope_users(
            db.query(FactAssistantTurn.user_id.label("user_id"))
            .join(User, User.id == FactAssistantTurn.user_id)
            .filter(
                FactAssistantTurn.created_at >= window.range_start_dt,
                FactAssistantTurn.created_at <= window.range_end_dt,
            ),
            include_admins=include_admins,
        )
        login_active_users = self._scope_users(
            db.query(UserLoginDaily.user_id.label("user_id"))
            .join(User, User.id == UserLoginDaily.user_id)
            .filter(
                UserLoginDaily.login_date >= window.range_start_day,
                UserLoginDaily.login_date <= window.range_end_day,
            ),
            include_admins=include_admins,
        )
        active_union = assistant_active_users.union(login_active_users).subquery()
        active_users_last_n_days = int(db.query(func.count(func.distinct(active_union.c.user_id))).scalar() or 0)

        files_by_type: List[Dict[str, Any]] = []
        users_by_department: List[Dict[str, Any]] = []
        top_users_by_messages: List[Dict[str, Any]] = []
        top_uploaders: List[Dict[str, Any]] = []
        if include_extended:
            files_by_type = [
                {"file_type": file_type or "unknown", "count": int(count or 0), "size_bytes": int(size_bytes or 0)}
                for file_type, count, size_bytes in (
                    self._scope_users(
                        db.query(File.file_type, func.count(File.id), func.coalesce(func.sum(File.file_size), 0))
                        .join(User, User.id == File.user_id),
                        include_admins=include_admins,
                    )
                    .group_by(File.file_type)
                    .all()
                )
            ]
            users_by_department = [
                {"user_id": "", "email": department or "Unknown", "count": int(count or 0), "size_bytes": None}
                for department, count in (
                    self._scope_users(db.query(User.department, func.count(User.id)), include_admins=include_admins)
                    .group_by(User.department)
                    .all()
                )
            ]
            top_users_by_messages = [
                {"user_id": str(uid), "email": email, "count": int(count or 0)}
                for uid, email, count in (
                    self._scope_users(
                        db.query(User.id, User.email, func.count(FactAssistantTurn.message_id))
                        .join(FactAssistantTurn, FactAssistantTurn.user_id == User.id)
                        .filter(
                            FactAssistantTurn.created_at >= window.range_start_dt,
                            FactAssistantTurn.created_at <= window.range_end_dt,
                        ),
                        include_admins=include_admins,
                    )
                    .group_by(User.id, User.email)
                    .order_by(func.count(FactAssistantTurn.message_id).desc())
                    .limit(5)
                    .all()
                )
            ]
            top_uploaders = [
                {"user_id": str(uid), "email": email, "count": int(count or 0), "size_bytes": int(size_bytes or 0)}
                for uid, email, count, size_bytes in (
                    self._scope_users(
                        db.query(User.id, User.email, func.count(File.id), func.coalesce(func.sum(File.file_size), 0))
                        .join(File, File.user_id == User.id)
                        .filter(File.created_at >= window.range_start_dt, File.created_at <= window.range_end_dt),
                        include_admins=include_admins,
                    )
                    .group_by(User.id, User.email)
                    .order_by(func.coalesce(func.sum(File.file_size), 0).desc())
                    .limit(5)
                    .all()
                )
            ]

        def _empty_model_rollup(bucket: str) -> Dict[str, Any]:
            return {
                "model": bucket,
                "message_count": 0,
                "effective_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": Decimal("0"),
                "_latency_sum_ms": 0,
                "_latency_samples": 0,
                "_chat_count": 0,
                "_non_chat_count": 0,
                "_process_counts": {},
            }

        def _accumulate_model_rollups(
            target: Dict[str, Dict[str, Any]],
            *,
            provider: Any,
            model: Any,
            message_count: Any,
            input_tokens: Any,
            output_tokens: Any,
            total_tokens: Any,
            cost_usd: Any,
            latency_sum_ms: Any,
            latency_samples: Any,
            source: str,
            process_key: Any,
        ) -> None:
            normalized_count = int(message_count or 0)
            if normalized_count <= 0:
                return
            bucket = normalize_runtime_bucket(
                str(provider or "").strip() or None,
                str(model or "").strip() or None,
            )
            rollup = target.setdefault(bucket, _empty_model_rollup(bucket))
            rollup["message_count"] += normalized_count
            rollup["effective_input_tokens"] += int(input_tokens or 0)
            rollup["output_tokens"] += int(output_tokens or 0)
            rollup["total_tokens"] += int(total_tokens or 0)
            rollup["cost_usd"] += Decimal(str(cost_usd or 0))
            rollup["_latency_sum_ms"] += int(latency_sum_ms or 0)
            rollup["_latency_samples"] += int(latency_samples or 0)
            if source == "non_chat":
                rollup["_non_chat_count"] += normalized_count
            else:
                rollup["_chat_count"] += normalized_count
            normalized_process = str(process_key or "").strip().lower()
            if normalized_process:
                process_counts = rollup.setdefault("_process_counts", {})
                process_counts[normalized_process] = int(process_counts.get(normalized_process, 0)) + normalized_count

        def _finalize_model_rollups(source_rollups: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            for rollup in source_rollups.values():
                message_count = int(rollup["message_count"] or 0)
                latency_samples = int(rollup["_latency_samples"] or 0)
                latency_sum_ms = int(rollup["_latency_sum_ms"] or 0)
                chat_count = int(rollup["_chat_count"] or 0)
                non_chat_count = int(rollup["_non_chat_count"] or 0)
                if chat_count > 0 and non_chat_count > 0:
                    source = "mixed"
                elif non_chat_count > 0:
                    source = "non_chat"
                else:
                    source = "chat"
                process_counts = rollup.get("_process_counts") if isinstance(rollup.get("_process_counts"), dict) else {}
                sorted_processes = sorted(
                    process_counts.items(),
                    key=lambda item: (-int(item[1] or 0), str(item[0] or "")),
                )
                process_labels: List[str] = []
                seen_process_labels: set[str] = set()
                for process_key, _process_count in sorted_processes:
                    label = _format_process_label(process_key)
                    if not label or label in seen_process_labels:
                        continue
                    seen_process_labels.add(label)
                    process_labels.append(label)
                if not process_labels:
                    process_labels = ["Chat"] if source == "chat" else ["Unknown operation"]
                rows.append(
                    {
                        "model": rollup["model"],
                        "source": source,
                        "processes": process_labels,
                        "message_count": message_count,
                        "effective_input_tokens": int(rollup["effective_input_tokens"] or 0),
                        "output_tokens": int(rollup["output_tokens"] or 0),
                        "total_tokens": int(rollup["total_tokens"] or 0),
                        "avg_response_latency_ms": (
                            float(latency_sum_ms) / float(latency_samples)
                            if latency_samples > 0
                            else None
                        ),
                        "cost_usd": _to_float(rollup["cost_usd"], digits=8),
                    }
                )
            return _sort_model_usage_rows(rows)

        chat_model_rows = (
            db.query(
                AggModelDay.model_provider,
                AggModelDay.model_name,
                func.sum(AggModelDay.message_count),
                func.sum(AggModelDay.input_tokens),
                func.sum(AggModelDay.output_tokens),
                func.sum(AggModelDay.total_tokens),
                func.sum(AggModelDay.cost_usd),
                func.sum(AggModelDay.latency_sum_ms),
                func.sum(AggModelDay.latency_samples),
            )
            .filter(
                AggModelDay.scope == scope,
                AggModelDay.metric_date >= window.range_start_day,
                AggModelDay.metric_date <= window.range_end_day,
            )
            .group_by(AggModelDay.model_provider, AggModelDay.model_name)
            .all()
        )

        non_chat_model_rows = (
            db.query(
                AggModelUsageDay.model_provider,
                AggModelUsageDay.model_name,
                AggModelUsageDay.operation_type,
                func.sum(AggModelUsageDay.call_count),
                func.sum(AggModelUsageDay.input_tokens),
                func.sum(AggModelUsageDay.output_tokens),
                func.sum(AggModelUsageDay.total_tokens),
                func.sum(AggModelUsageDay.cost_usd),
                func.sum(AggModelUsageDay.latency_sum_ms),
                func.sum(AggModelUsageDay.latency_samples),
            )
            .filter(
                AggModelUsageDay.scope == scope,
                AggModelUsageDay.source == "non_chat",
                AggModelUsageDay.metric_date >= window.range_start_day,
                AggModelUsageDay.metric_date <= window.range_end_day,
            )
            .group_by(
                AggModelUsageDay.model_provider,
                AggModelUsageDay.model_name,
                AggModelUsageDay.operation_type,
            )
            .all()
        )

        chat_model_rollups: Dict[str, Dict[str, Any]] = {}
        for (
            provider,
            model,
            msg_count,
            in_tok,
            out_tok,
            total_tok,
            cost_usd,
            lat_sum,
            lat_samples,
        ) in chat_model_rows:
            _accumulate_model_rollups(
                chat_model_rollups,
                provider=provider,
                model=model,
                message_count=msg_count,
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=total_tok,
                cost_usd=cost_usd,
                latency_sum_ms=lat_sum,
                latency_samples=lat_samples,
                source="chat",
                process_key="chat",
            )

        non_chat_model_rollups: Dict[str, Dict[str, Any]] = {}
        for (
            provider,
            model,
            operation_type,
            call_count,
            in_tok,
            out_tok,
            total_tok,
            cost_usd,
            lat_sum,
            lat_samples,
        ) in non_chat_model_rows:
            _accumulate_model_rollups(
                non_chat_model_rollups,
                provider=provider,
                model=model,
                message_count=call_count,
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=total_tok,
                cost_usd=cost_usd,
                latency_sum_ms=lat_sum,
                latency_samples=lat_samples,
                source="non_chat",
                process_key=operation_type,
            )

        model_rollups: Dict[str, Dict[str, Any]] = {
            bucket: {
                **dict(values),
                "_process_counts": dict(values.get("_process_counts") or {}),
            }
            for bucket, values in chat_model_rollups.items()
        }
        for bucket, values in non_chat_model_rollups.items():
            target = model_rollups.setdefault(bucket, _empty_model_rollup(bucket))
            target["message_count"] += int(values["message_count"] or 0)
            target["effective_input_tokens"] += int(values["effective_input_tokens"] or 0)
            target["output_tokens"] += int(values["output_tokens"] or 0)
            target["total_tokens"] += int(values["total_tokens"] or 0)
            target["cost_usd"] += Decimal(str(values["cost_usd"] or 0))
            target["_latency_sum_ms"] += int(values["_latency_sum_ms"] or 0)
            target["_latency_samples"] += int(values["_latency_samples"] or 0)
            target["_chat_count"] += int(values["_chat_count"] or 0)
            target["_non_chat_count"] += int(values["_non_chat_count"] or 0)
            target_process_counts = target.setdefault("_process_counts", {})
            value_process_counts = values.get("_process_counts") if isinstance(values.get("_process_counts"), dict) else {}
            for process_key, process_count in value_process_counts.items():
                normalized_process = str(process_key or "").strip().lower()
                if not normalized_process:
                    continue
                target_process_counts[normalized_process] = (
                    int(target_process_counts.get(normalized_process, 0)) + int(process_count or 0)
                )

        model_usage_chat_last_n_days = _finalize_model_rollups(chat_model_rollups)
        model_usage_non_chat_last_n_days = _finalize_model_rollups(non_chat_model_rollups)
        model_usage_last_n_days = _finalize_model_rollups(model_rollups)

        chat_model_daily_rows = (
            db.query(
                AggModelDay.metric_date,
                AggModelDay.model_provider,
                AggModelDay.model_name,
                func.sum(AggModelDay.cost_usd),
            )
            .filter(
                AggModelDay.scope == scope,
                AggModelDay.metric_date >= window.series_start_day,
                AggModelDay.metric_date <= window.range_end_day,
            )
            .group_by(AggModelDay.metric_date, AggModelDay.model_provider, AggModelDay.model_name)
            .all()
        )

        non_chat_model_daily_rows = (
            db.query(
                AggModelUsageDay.metric_date,
                AggModelUsageDay.model_provider,
                AggModelUsageDay.model_name,
                func.sum(AggModelUsageDay.cost_usd),
            )
            .filter(
                AggModelUsageDay.scope == scope,
                AggModelUsageDay.source == "non_chat",
                AggModelUsageDay.metric_date >= window.series_start_day,
                AggModelUsageDay.metric_date <= window.range_end_day,
            )
            .group_by(AggModelUsageDay.metric_date, AggModelUsageDay.model_provider, AggModelUsageDay.model_name)
            .all()
        )

        def _build_cost_map(rows: List[Any]) -> Dict[date, Dict[str, Decimal]]:
            cost_map: Dict[date, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
            for metric_day, provider, model, cost_usd in rows:
                if not isinstance(metric_day, date):
                    continue
                bucket = normalize_runtime_bucket(
                    str(provider or "").strip() or None,
                    str(model or "").strip() or None,
                )
                cost_map[metric_day][bucket] += Decimal(str(cost_usd or 0))
            return cost_map

        def _build_cost_series(cost_map: Dict[date, Dict[str, Decimal]]) -> List[Dict[str, Any]]:
            timeseries: List[Dict[str, Any]] = []
            for day in window.day_sequence:
                model_costs = cost_map.get(day, {})
                total_day_cost = sum(model_costs.values(), Decimal("0"))
                timeseries.append(
                    {
                        "date": day.strftime("%Y-%m-%d"),
                        "total": _to_float(total_day_cost, digits=8),
                        "models": {
                            bucket: _to_float(amount, digits=8)
                            for bucket, amount in sorted(
                                model_costs.items(),
                                key=lambda item: sort_bucket_key(item[0]),
                            )
                            if amount
                        },
                    }
                )
            return timeseries

        model_costs_chat_by_day = _build_cost_map(chat_model_daily_rows)
        model_costs_non_chat_by_day = _build_cost_map(non_chat_model_daily_rows)

        model_costs_by_day: Dict[date, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
        for day_map in (model_costs_chat_by_day, model_costs_non_chat_by_day):
            for metric_day, model_costs in day_map.items():
                for bucket, amount in model_costs.items():
                    model_costs_by_day[metric_day][bucket] += Decimal(str(amount or 0))

        model_cost_timeseries_chat = _build_cost_series(model_costs_chat_by_day)
        model_cost_timeseries_non_chat = _build_cost_series(model_costs_non_chat_by_day)
        model_cost_timeseries = _build_cost_series(model_costs_by_day)

        approx_avg_response_secs = (
            float(assistant_usage_range["avg_response_latency_ms"]) / 1000.0
            if assistant_usage_range.get("avg_response_latency_ms") is not None
            else 0.0
        )
        assistant_cost_last_n_days = _to_float(assistant_usage_range.get("cost_usd", 0.0), digits=8)
        non_chat_cost_decimal = sum(
            (Decimal(str(rollup.get("cost_usd", 0) or 0)) for rollup in non_chat_model_rollups.values()),
            Decimal("0"),
        )
        non_chat_cost_last_n_days = _to_float(non_chat_cost_decimal, digits=8)
        total_model_cost_last_n_days = _to_float(
            Decimal(str(assistant_cost_last_n_days)) + non_chat_cost_decimal,
            digits=8,
        )

        return {
            "generated_at": now.isoformat(),
            "range_start": window.range_start_dt.isoformat(),
            "range_end": window.range_end_dt.isoformat(),
            "days": days,
            "reporting_timezone": DEFAULT_REPORTING_TIMEZONE,
            "total_users": total_users,
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "total_files": total_files,
            "total_storage_bytes": total_storage_bytes,
            "messages_last_n_days": int(messages_last_n_days),
            "file_uploads_last_n_days": int(file_uploads_last_n_days),
            "users_per_day": users_per_day if include_extended else [],
            "conversations_per_day": conversations_per_day,
            "messages_per_day": messages_per_day,
            "file_uploads_per_day": file_uploads_per_day if include_extended else [],
            "active_users_per_day": active_users_per_day,
            "active_users_last_n_days": active_users_last_n_days,
            "files_by_type": files_by_type,
            "users_by_department": users_by_department,
            "top_users_by_messages": top_users_by_messages,
            "top_uploaders": top_uploaders,
            "approx_avg_response_secs": approx_avg_response_secs,
            "assistant_usage_last_n_days": assistant_usage_range,
            "assistant_usage_lifetime": assistant_usage_lifetime,
            "model_usage_last_n_days": model_usage_last_n_days,
            "model_usage_chat_last_n_days": model_usage_chat_last_n_days,
            "model_usage_non_chat_last_n_days": model_usage_non_chat_last_n_days,
            "assistant_cost_last_n_days": assistant_cost_last_n_days,
            "non_chat_cost_last_n_days": non_chat_cost_last_n_days,
            "total_model_cost_last_n_days": total_model_cost_last_n_days,
            "model_cost_timeseries": model_cost_timeseries,
            "model_cost_timeseries_chat": model_cost_timeseries_chat,
            "model_cost_timeseries_non_chat": model_cost_timeseries_non_chat,
        }
