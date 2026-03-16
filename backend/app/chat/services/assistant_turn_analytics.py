"""Analytics rollup sync for finalized assistant turns."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...database.models import (
    AdminUserRollup,
    AggModelDay,
    AggToolDay,
    AggUsageDay,
    AggUsageMinute,
    ChatRun,
    Conversation,
    FactAssistantTurn,
    FactToolCall,
    Message,
    ToolCall,
    User,
)


class AssistantTurnAnalyticsService:
    """Synchronize assistant-turn facts and aggregate rollups."""

    def sync_rollups(
        self,
        *,
        db: Session,
        conversation: Conversation,
        message: Message,
        run: Optional[ChatRun],
        usage_payload: Dict[str, Any],
    ) -> None:
        created_at = message.created_at or datetime.now(timezone.utc)
        if created_at.tzinfo is not None:
            created_at_utc = created_at.astimezone(timezone.utc)
        else:
            created_at_utc = created_at.replace(tzinfo=timezone.utc)

        day_start = created_at_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)
        metric_date = created_at_utc.date()
        minute_bucket = created_at_utc.replace(second=0, microsecond=0)

        try:
            tool_rows_query = db.query(ToolCall)
            fact_tool_query = db.query(FactToolCall)
        except Exception:
            return
        if not all(hasattr(tool_rows_query, attr) for attr in ("filter", "all")):
            return
        if not all(hasattr(fact_tool_query, attr) for attr in ("filter", "all", "delete")):
            return

        # Rollups should include total usage for the full turn (including tool loop),
        # not only the largest context snapshot.
        input_tokens = (
            self._coerce_int(usage_payload.get("aggregated_input_tokens"))
            or self._coerce_int(usage_payload.get("input_tokens"))
            or 0
        )
        output_tokens = (
            self._coerce_int(usage_payload.get("aggregated_output_tokens"))
            or self._coerce_int(usage_payload.get("output_tokens"))
            or 0
        )
        total_tokens = (
            self._coerce_int(usage_payload.get("aggregated_total_tokens"))
            or self._coerce_int(usage_payload.get("total_tokens"))
            or max(0, input_tokens + output_tokens)
        )
        reasoning_output_tokens = self._coerce_int(usage_payload.get("reasoning_output_tokens")) or 0
        tool_rows = tool_rows_query.filter(ToolCall.message_id == message.id).all()
        tool_call_count = len(tool_rows)
        latency_ms = (
            int(message.response_latency_ms)
            if isinstance(message.response_latency_ms, int) and message.response_latency_ms >= 0
            else None
        )
        cost_usd = Decimal(str(message.cost_usd or 0))
        existing_fact = db.query(FactAssistantTurn).filter(FactAssistantTurn.message_id == message.id).first()
        had_existing_fact = existing_fact is not None

        old_values = {
            "messages_count": 1 if had_existing_fact else 0,
            "input_tokens": int(getattr(existing_fact, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(existing_fact, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(existing_fact, "total_tokens", 0) or 0),
            "cost_usd": Decimal(str(getattr(existing_fact, "cost_usd", 0) or 0)),
            "latency_sum_ms": int(getattr(existing_fact, "latency_ms", 0) or 0),
            "latency_samples": 1 if getattr(existing_fact, "latency_ms", None) is not None else 0,
            "tool_call_count": int(getattr(existing_fact, "tool_call_count", 0) or 0),
            "model_provider": getattr(existing_fact, "model_provider", None),
            "model_name": getattr(existing_fact, "model_name", None),
        }
        new_values = {
            "messages_count": 1,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "latency_sum_ms": int(latency_ms or 0),
            "latency_samples": 1 if latency_ms is not None else 0,
            "tool_call_count": tool_call_count,
            "model_provider": message.model_provider,
            "model_name": message.model_name,
        }

        if existing_fact is None:
            existing_fact = FactAssistantTurn(message_id=message.id)
            db.add(existing_fact)
        existing_fact.conversation_id = conversation.id
        existing_fact.run_id = run.id if run is not None else None
        existing_fact.user_id = conversation.user_id
        existing_fact.project_id = conversation.project_id
        existing_fact.model_provider = message.model_provider
        existing_fact.model_name = message.model_name
        existing_fact.input_tokens = input_tokens
        existing_fact.output_tokens = output_tokens
        existing_fact.total_tokens = total_tokens
        existing_fact.reasoning_output_tokens = reasoning_output_tokens
        existing_fact.cost_usd = cost_usd
        existing_fact.latency_ms = latency_ms
        existing_fact.tool_call_count = tool_call_count
        existing_fact.created_at = created_at_utc
        db.flush()

        existing_fact_tools = fact_tool_query.filter(FactToolCall.message_id == message.id).all()
        old_tool_rollup: Dict[str, Dict[str, int]] = {}
        for fact_tool in existing_fact_tools:
            tool_name = str(fact_tool.tool_name or "").strip().lower()
            if not tool_name:
                continue
            bucket = old_tool_rollup.setdefault(tool_name, {"call_count": 0, "error_count": 0, "duration_sum_ms": 0})
            bucket["call_count"] += 1
            bucket["error_count"] += 1 if bool(fact_tool.is_error) else 0
            if isinstance(fact_tool.duration_ms, int) and fact_tool.duration_ms >= 0:
                bucket["duration_sum_ms"] += int(fact_tool.duration_ms)

        fact_tool_query.filter(FactToolCall.message_id == message.id).delete(synchronize_session=False)
        new_tool_rollup: Dict[str, Dict[str, int]] = {}
        for tool_row in tool_rows:
            tool_name = str(tool_row.tool_name or "").strip().lower()
            if not tool_name:
                continue
            is_error = bool(tool_row.error_jsonb) or str(tool_row.status or "").strip().lower() in {"failed", "cancelled"}
            duration_ms: Optional[int] = None
            if isinstance(tool_row.started_at, datetime) and isinstance(tool_row.finished_at, datetime):
                delta_ms = int((tool_row.finished_at - tool_row.started_at).total_seconds() * 1000)
                if delta_ms >= 0:
                    duration_ms = delta_ms

            db.add(
                FactToolCall(
                    message_id=message.id,
                    run_id=run.id if run is not None else None,
                    tool_name=tool_name,
                    is_error=is_error,
                    duration_ms=duration_ms,
                    created_at=created_at_utc,
                )
            )
            bucket = new_tool_rollup.setdefault(tool_name, {"call_count": 0, "error_count": 0, "duration_sum_ms": 0})
            bucket["call_count"] += 1
            bucket["error_count"] += 1 if is_error else 0
            if isinstance(duration_ms, int) and duration_ms >= 0:
                bucket["duration_sum_ms"] += int(duration_ms)
        db.flush()

        user_role = db.query(User.role).filter(User.id == conversation.user_id).scalar()
        is_admin_user = str(user_role or "").strip().lower() == "admin"
        scopes = ["all"]
        if not is_admin_user:
            scopes.append("non_admin")

        first_turn_today = False
        if (not had_existing_fact) and conversation.user_id:
            existing_today = (
                db.query(FactAssistantTurn.message_id)
                .filter(
                    FactAssistantTurn.user_id == conversation.user_id,
                    FactAssistantTurn.message_id != message.id,
                    FactAssistantTurn.created_at >= day_start,
                    FactAssistantTurn.created_at <= day_end,
                )
                .first()
            )
            first_turn_today = existing_today is None

        usage_delta = {
            "messages_count": new_values["messages_count"] - old_values["messages_count"],
            "input_tokens": new_values["input_tokens"] - old_values["input_tokens"],
            "output_tokens": new_values["output_tokens"] - old_values["output_tokens"],
            "total_tokens": new_values["total_tokens"] - old_values["total_tokens"],
            "cost_usd": new_values["cost_usd"] - old_values["cost_usd"],
            "latency_sum_ms": new_values["latency_sum_ms"] - old_values["latency_sum_ms"],
            "latency_samples": new_values["latency_samples"] - old_values["latency_samples"],
            "tool_call_count": new_values["tool_call_count"] - old_values["tool_call_count"],
        }

        for scope in scopes:
            self._apply_usage_rollup_delta(
                db=db,
                scope=scope,
                metric_date=metric_date,
                minute_bucket=minute_bucket,
                delta=usage_delta,
                increment_active_users=first_turn_today,
            )
            self._apply_model_rollup_delta(
                db=db,
                scope=scope,
                metric_date=metric_date,
                old_values=old_values,
                new_values=new_values,
            )
            self._apply_tool_rollup_delta(
                db=db,
                scope=scope,
                metric_date=metric_date,
                old_tool_rollup=old_tool_rollup,
                new_tool_rollup=new_tool_rollup,
            )
        self._apply_admin_user_rollup_delta(
            db=db,
            user_id=conversation.user_id,
            turn_count_delta=int(usage_delta["messages_count"]),
            cost_delta=Decimal(str(usage_delta["cost_usd"] or 0)),
            last_assistant_turn_at=created_at_utc,
        )

    def _apply_usage_rollup_delta(
        self,
        *,
        db: Session,
        scope: str,
        metric_date: date,
        minute_bucket: datetime,
        delta: Dict[str, Any],
        increment_active_users: bool,
    ) -> None:
        day_row = (
            db.query(AggUsageDay)
            .filter(AggUsageDay.metric_date == metric_date, AggUsageDay.scope == scope)
            .first()
        )
        if day_row is None:
            day_row = AggUsageDay(metric_date=metric_date, scope=scope)
            db.add(day_row)

        minute_row = (
            db.query(AggUsageMinute)
            .filter(AggUsageMinute.bucket_minute == minute_bucket, AggUsageMinute.scope == scope)
            .first()
        )
        if minute_row is None:
            minute_row = AggUsageMinute(bucket_minute=minute_bucket, scope=scope)
            db.add(minute_row)

        for row in (day_row, minute_row):
            row.messages_count = max(0, int(row.messages_count or 0) + int(delta["messages_count"]))
            row.assistant_messages_count = max(
                0,
                int(row.assistant_messages_count or 0) + int(delta["messages_count"]),
            )
            row.input_tokens = max(0, int(row.input_tokens or 0) + int(delta["input_tokens"]))
            row.output_tokens = max(0, int(row.output_tokens or 0) + int(delta["output_tokens"]))
            row.total_tokens = max(0, int(row.total_tokens or 0) + int(delta["total_tokens"]))
            row.cost_usd = Decimal(str(row.cost_usd or 0)) + Decimal(str(delta["cost_usd"] or 0))
            row.latency_sum_ms = max(0, int(row.latency_sum_ms or 0) + int(delta["latency_sum_ms"]))
            row.latency_samples = max(0, int(row.latency_samples or 0) + int(delta["latency_samples"]))
            row.tool_call_count = max(0, int(row.tool_call_count or 0) + int(delta["tool_call_count"]))
            row.updated_at = datetime.now(timezone.utc)

        if increment_active_users:
            day_row.active_users = max(0, int(day_row.active_users or 0) + 1)

        db.flush()

    def _apply_model_rollup_delta(
        self,
        *,
        db: Session,
        scope: str,
        metric_date: date,
        old_values: Dict[str, Any],
        new_values: Dict[str, Any],
    ) -> None:
        def _apply(
            *,
            model_provider: Optional[str],
            model_name: Optional[str],
            sign: int,
            values: Dict[str, Any],
        ) -> None:
            normalized_provider = str(model_provider or "unknown").strip() or "unknown"
            normalized_model = str(model_name or "unknown").strip() or "unknown"
            row = (
                db.query(AggModelDay)
                .filter(
                    AggModelDay.metric_date == metric_date,
                    AggModelDay.scope == scope,
                    AggModelDay.model_provider == normalized_provider,
                    AggModelDay.model_name == normalized_model,
                )
                .first()
            )
            if row is None:
                row = AggModelDay(
                    metric_date=metric_date,
                    scope=scope,
                    model_provider=normalized_provider,
                    model_name=normalized_model,
                )
                db.add(row)

            row.message_count = max(0, int(row.message_count or 0) + sign * int(values["messages_count"]))
            row.input_tokens = max(0, int(row.input_tokens or 0) + sign * int(values["input_tokens"]))
            row.output_tokens = max(0, int(row.output_tokens or 0) + sign * int(values["output_tokens"]))
            row.total_tokens = max(0, int(row.total_tokens or 0) + sign * int(values["total_tokens"]))
            row.cost_usd = Decimal(str(row.cost_usd or 0)) + (Decimal(str(values["cost_usd"] or 0)) * sign)
            row.latency_sum_ms = max(0, int(row.latency_sum_ms or 0) + sign * int(values["latency_sum_ms"]))
            row.latency_samples = max(0, int(row.latency_samples or 0) + sign * int(values["latency_samples"]))
            row.tool_call_count = max(0, int(row.tool_call_count or 0) + sign * int(values["tool_call_count"]))
            row.updated_at = datetime.now(timezone.utc)

        old_provider = old_values.get("model_provider")
        old_model = old_values.get("model_name")
        new_provider = new_values.get("model_provider")
        new_model = new_values.get("model_name")

        old_key = (
            str(old_provider or "unknown").strip() or "unknown",
            str(old_model or "unknown").strip() or "unknown",
        )
        new_key = (
            str(new_provider or "unknown").strip() or "unknown",
            str(new_model or "unknown").strip() or "unknown",
        )
        model_changed = old_key != new_key
        if model_changed:
            if old_values["messages_count"] > 0:
                _apply(model_provider=old_provider, model_name=old_model, sign=-1, values=old_values)
            _apply(model_provider=new_provider, model_name=new_model, sign=1, values=new_values)
            db.flush()
            return

        delta_values = {
            "messages_count": int(new_values["messages_count"]) - int(old_values["messages_count"]),
            "input_tokens": int(new_values["input_tokens"]) - int(old_values["input_tokens"]),
            "output_tokens": int(new_values["output_tokens"]) - int(old_values["output_tokens"]),
            "total_tokens": int(new_values["total_tokens"]) - int(old_values["total_tokens"]),
            "cost_usd": Decimal(str(new_values["cost_usd"] or 0)) - Decimal(str(old_values["cost_usd"] or 0)),
            "latency_sum_ms": int(new_values["latency_sum_ms"]) - int(old_values["latency_sum_ms"]),
            "latency_samples": int(new_values["latency_samples"]) - int(old_values["latency_samples"]),
            "tool_call_count": int(new_values["tool_call_count"]) - int(old_values["tool_call_count"]),
        }
        _apply(model_provider=new_provider, model_name=new_model, sign=1, values=delta_values)
        db.flush()

    def _apply_tool_rollup_delta(
        self,
        *,
        db: Session,
        scope: str,
        metric_date: date,
        old_tool_rollup: Dict[str, Dict[str, int]],
        new_tool_rollup: Dict[str, Dict[str, int]],
    ) -> None:
        all_tools = set(old_tool_rollup.keys()) | set(new_tool_rollup.keys())
        for tool_name in all_tools:
            old_values = old_tool_rollup.get(tool_name, {"call_count": 0, "error_count": 0, "duration_sum_ms": 0})
            new_values = new_tool_rollup.get(tool_name, {"call_count": 0, "error_count": 0, "duration_sum_ms": 0})
            delta_calls = int(new_values["call_count"]) - int(old_values["call_count"])
            delta_errors = int(new_values["error_count"]) - int(old_values["error_count"])
            delta_duration = int(new_values["duration_sum_ms"]) - int(old_values["duration_sum_ms"])
            if delta_calls == 0 and delta_errors == 0 and delta_duration == 0:
                continue

            row = (
                db.query(AggToolDay)
                .filter(
                    AggToolDay.metric_date == metric_date,
                    AggToolDay.scope == scope,
                    AggToolDay.tool_name == tool_name,
                )
                .first()
            )
            if row is None:
                row = AggToolDay(metric_date=metric_date, scope=scope, tool_name=tool_name)
                db.add(row)

            previous_calls = int(row.call_count or 0)
            previous_duration_total = int((row.avg_duration_ms or 0) * previous_calls) if row.avg_duration_ms is not None else 0
            next_calls = max(0, previous_calls + delta_calls)
            next_duration_total = max(0, previous_duration_total + delta_duration)

            row.call_count = next_calls
            row.error_count = max(0, int(row.error_count or 0) + delta_errors)
            row.avg_duration_ms = int(round(next_duration_total / next_calls)) if next_calls > 0 else None
            row.updated_at = datetime.now(timezone.utc)

        db.flush()

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _apply_admin_user_rollup_delta(
        self,
        *,
        db: Session,
        user_id: Optional[str],
        turn_count_delta: int,
        cost_delta: Decimal,
        last_assistant_turn_at: datetime,
    ) -> None:
        if not user_id:
            return
        normalized_user_id = str(user_id)
        normalized_turn_delta = int(turn_count_delta or 0)
        normalized_cost_delta = Decimal(str(cost_delta or 0))
        insert_stmt = pg_insert(AdminUserRollup).values(
            user_id=normalized_user_id,
            conversation_count=(
                select(func.count(Conversation.id))
                .where(Conversation.user_id == normalized_user_id)
                .scalar_subquery()
            ),
            assistant_turn_count=max(0, normalized_turn_delta),
            total_cost_usd=max(Decimal("0"), normalized_cost_delta),
            last_assistant_turn_at=last_assistant_turn_at if normalized_turn_delta > 0 else None,
        )
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[AdminUserRollup.user_id],
                set_={
                    "assistant_turn_count": func.greatest(
                        0,
                        AdminUserRollup.assistant_turn_count + normalized_turn_delta,
                    ),
                    "total_cost_usd": func.greatest(
                        Decimal("0"),
                        AdminUserRollup.total_cost_usd + normalized_cost_delta,
                    ),
                    "last_assistant_turn_at": func.greatest(
                        func.coalesce(
                            AdminUserRollup.last_assistant_turn_at,
                            last_assistant_turn_at,
                        ),
                        last_assistant_turn_at,
                    ),
                    "updated_at": func.now(),
                },
            )
        )
        db.flush()
