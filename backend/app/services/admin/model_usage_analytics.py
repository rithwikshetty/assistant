"""Analytics rollup sync for non-chat model usage events."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...database.models import AggModelUsageDay, FactModelUsageEvent


class ModelUsageAnalyticsService:
    """Synchronize non-chat model usage facts and daily aggregates."""

    def sync_rollups(
        self,
        *,
        db: Session,
        event_id: str,
        payload: Dict[str, Any],
        is_admin_user: bool | None,
        fallback_created_at: datetime | None,
    ) -> bool:
        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id:
            raise ValueError("missing event_id")

        existing = (
            db.query(FactModelUsageEvent.event_id)
            .filter(FactModelUsageEvent.event_id == normalized_event_id)
            .first()
        )
        if existing is not None:
            return False

        source = self._normalize_source(payload.get("source"))
        operation_type = self._normalize_operation_type(payload.get("operation_type"))
        user_id = self._normalize_uuid_identifier(payload.get("user_id"))
        conversation_id = self._normalize_uuid_identifier(payload.get("conversation_id"))
        project_id = self._normalize_uuid_identifier(payload.get("project_id"))
        model_provider = self._normalize_provider(payload.get("model_provider"))
        model_name = self._normalize_model_name(payload.get("model_name"))

        call_count = self._coerce_int(payload.get("call_count"), default=1, minimum=1)
        input_tokens = self._coerce_int(payload.get("input_tokens"))
        output_tokens = self._coerce_int(payload.get("output_tokens"))
        total_tokens = self._coerce_int(payload.get("total_tokens"))
        if total_tokens <= 0:
            total_tokens = max(0, input_tokens + output_tokens)
        cache_creation_input_tokens = self._coerce_int(payload.get("cache_creation_input_tokens"))
        cache_read_input_tokens = self._coerce_int(payload.get("cache_read_input_tokens"))

        duration_seconds = self._coerce_decimal(payload.get("duration_seconds"))
        latency_ms_raw = payload.get("latency_ms")
        latency_ms = None
        if latency_ms_raw is not None:
            latency_ms = self._coerce_int(latency_ms_raw)

        cost_usd = self._coerce_decimal(payload.get("cost_usd"))
        metadata = payload.get("usage_metadata") if isinstance(payload.get("usage_metadata"), dict) else {}

        created_at = self._parse_created_at(payload.get("created_at"), fallback=fallback_created_at)
        metric_date = created_at.date()

        db.add(
            FactModelUsageEvent(
                event_id=normalized_event_id,
                source=source,
                operation_type=operation_type,
                user_id=user_id,
                conversation_id=conversation_id,
                project_id=project_id,
                model_provider=model_provider,
                model_name=model_name,
                call_count=call_count,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                duration_seconds=duration_seconds,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                metadata_jsonb=metadata,
                created_at=created_at,
            )
        )

        scopes = ["all"]
        if user_id is not None and not bool(is_admin_user):
            scopes.append("non_admin")

        for scope in scopes:
            self._upsert_aggregate_row(
                db=db,
                metric_date=metric_date,
                scope=scope,
                source=source,
                operation_type=operation_type,
                model_provider=model_provider,
                model_name=model_name,
                call_count=call_count,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                duration_seconds=duration_seconds,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )

        db.flush()
        return True

    @staticmethod
    def _normalize_source(raw_source: Any) -> str:
        normalized = str(raw_source or "non_chat").strip().lower()
        if normalized in {"chat", "non_chat"}:
            return normalized
        return "non_chat"

    @staticmethod
    def _normalize_operation_type(raw_value: Any) -> str:
        normalized = str(raw_value or "unknown_operation").strip().lower().replace(" ", "_")
        return normalized or "unknown_operation"

    @staticmethod
    def _normalize_provider(raw_value: Any) -> str:
        normalized = str(raw_value or "unknown").strip().lower()
        return normalized or "unknown"

    @staticmethod
    def _normalize_model_name(raw_value: Any) -> str:
        normalized = str(raw_value or "unknown").strip()
        return normalized or "unknown"

    @staticmethod
    def _normalize_uuid_identifier(raw_value: Any) -> str | None:
        candidate = str(raw_value or "").strip()
        if not candidate:
            return None
        try:
            UUID(candidate)
        except Exception:
            return None
        return candidate

    @staticmethod
    def _coerce_int(raw_value: Any, *, default: int = 0, minimum: int = 0) -> int:
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, parsed)

    @staticmethod
    def _coerce_decimal(raw_value: Any) -> Decimal:
        try:
            parsed = Decimal(str(raw_value))
        except Exception:
            return Decimal("0")
        return parsed if parsed >= 0 else Decimal("0")

    @staticmethod
    def _parse_created_at(raw_value: Any, *, fallback: datetime | None) -> datetime:
        if isinstance(raw_value, datetime):
            if raw_value.tzinfo is None:
                return raw_value.replace(tzinfo=timezone.utc)
            return raw_value.astimezone(timezone.utc)
        if isinstance(raw_value, str):
            candidate = raw_value.strip()
            if candidate:
                try:
                    parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        return parsed.replace(tzinfo=timezone.utc)
                    return parsed.astimezone(timezone.utc)
                except ValueError:
                    pass
        if isinstance(fallback, datetime):
            if fallback.tzinfo is None:
                return fallback.replace(tzinfo=timezone.utc)
            return fallback.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _upsert_aggregate_row(
        *,
        db: Session,
        metric_date,
        scope: str,
        source: str,
        operation_type: str,
        model_provider: str,
        model_name: str,
        call_count: int,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        duration_seconds: Decimal,
        cost_usd: Decimal,
        latency_ms: int | None,
    ) -> None:
        insert_stmt = pg_insert(AggModelUsageDay).values(
            metric_date=metric_date,
            scope=scope,
            source=source,
            operation_type=operation_type,
            model_provider=model_provider,
            model_name=model_name,
            call_count=call_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            duration_seconds_sum=duration_seconds,
            cost_usd=cost_usd,
            latency_sum_ms=(latency_ms or 0),
            latency_samples=(1 if latency_ms is not None else 0),
        )
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[
                    AggModelUsageDay.metric_date,
                    AggModelUsageDay.scope,
                    AggModelUsageDay.source,
                    AggModelUsageDay.operation_type,
                    AggModelUsageDay.model_provider,
                    AggModelUsageDay.model_name,
                ],
                set_={
                    "call_count": AggModelUsageDay.call_count + insert_stmt.excluded.call_count,
                    "input_tokens": AggModelUsageDay.input_tokens + insert_stmt.excluded.input_tokens,
                    "output_tokens": AggModelUsageDay.output_tokens + insert_stmt.excluded.output_tokens,
                    "total_tokens": AggModelUsageDay.total_tokens + insert_stmt.excluded.total_tokens,
                    "duration_seconds_sum": (
                        AggModelUsageDay.duration_seconds_sum + insert_stmt.excluded.duration_seconds_sum
                    ),
                    "cost_usd": AggModelUsageDay.cost_usd + insert_stmt.excluded.cost_usd,
                    "latency_sum_ms": AggModelUsageDay.latency_sum_ms + insert_stmt.excluded.latency_sum_ms,
                    "latency_samples": AggModelUsageDay.latency_samples + insert_stmt.excluded.latency_samples,
                    "updated_at": func.now(),
                },
            )
        )


__all__ = ["ModelUsageAnalyticsService"]
