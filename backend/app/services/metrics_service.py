from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from ..database.models import (
    AggActivityDay,
    AggFeedbackDay,
    AggToolDay,
    BugReport,
    ChatRun,
    Conversation,
    FactAssistantTurn,
    FactToolCall,
    User,
    UserActivity,
    UserRedactionEntry,
)
from ..utils.roles import non_admin_role_filter
from ..utils.timezone_context import DEFAULT_REPORTING_TIMEZONE
from .usage_service import UsageService


def _severity_counts(rows: List[Tuple[str, int]]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for severity, count in rows:
        key = (severity or "unknown").lower()
        counts[key] += int(count or 0)
    return dict(counts)

def _resolve_datetime_window(
    *,
    now: datetime,
    days: int,
    start_date: Optional["date"],
    end_date: Optional["date"],
) -> tuple[datetime, datetime, int]:
    if start_date and end_date:
        range_start = min(start_date, end_date)
        range_end = max(start_date, end_date)
        start_dt = datetime.combine(range_start, datetime.min.time(), timezone.utc)
        end_exclusive_dt = datetime.combine(range_end + timedelta(days=1), datetime.min.time(), timezone.utc)
        effective_days = max(1, (range_end - range_start).days + 1)
        return start_dt, end_exclusive_dt, effective_days

    safe_days = max(1, days)
    # Keep implicit day windows aligned to calendar-day boundaries in UTC.
    # This prevents mixed-range math when combining daily aggregates
    # (agg_* tables) with timestamp-based facts/runs in one response.
    range_end = now.date()
    range_start = range_end - timedelta(days=safe_days - 1)
    start_dt = datetime.combine(range_start, datetime.min.time(), timezone.utc)
    end_exclusive_dt = datetime.combine(range_end + timedelta(days=1), datetime.min.time(), timezone.utc)
    return start_dt, end_exclusive_dt, safe_days


class MetricsService:
    def __init__(self, usage_service: UsageService | None = None) -> None:
        self._usage_service = usage_service or UsageService()

    def _feedback_counts(
        self,
        db: Session,
        *,
        include_admins: bool,
        start_db: datetime | None = None,
        end_exclusive_db: datetime | None = None,
    ) -> Dict[str, int]:
        scope = "all" if include_admins else "non_admin"
        query = (
            db.query(
                func.coalesce(func.sum(AggFeedbackDay.total_count), 0).label("total"),
                func.coalesce(func.sum(AggFeedbackDay.up_count), 0).label("up"),
                func.coalesce(func.sum(AggFeedbackDay.down_count), 0).label("down"),
                func.coalesce(func.sum(AggFeedbackDay.time_saved_minutes), 0).label("time_saved_minutes"),
                func.coalesce(func.sum(AggFeedbackDay.time_spent_minutes), 0).label("time_spent_minutes"),
            )
            .filter(AggFeedbackDay.scope == scope)
        )
        if start_db is not None:
            query = query.filter(AggFeedbackDay.metric_date >= start_db.date())
        if end_exclusive_db is not None:
            query = query.filter(AggFeedbackDay.metric_date < end_exclusive_db.date())
        row = query.one()
        return {
            "total": int(row.total or 0),
            "up": int(row.up or 0),
            "down": int(row.down or 0),
            "time_saved_minutes": int(row.time_saved_minutes or 0),
            "time_spent_minutes": int(row.time_spent_minutes or 0),
        }

    def get_bug_metrics(
        self,
        db: Session,
        *,
        include_admins: bool = False,
        start_date: Optional["date"] = None,
        end_date: Optional["date"] = None,
        days: int = 30,
    ) -> Dict:
        now = datetime.now(timezone.utc)
        start_db, end_exclusive_db, _ = _resolve_datetime_window(
            now=now,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        bug_query = db.query(BugReport.severity, func.count(BugReport.id)).join(User, User.id == BugReport.user_id)
        if not include_admins:
            bug_query = bug_query.filter(non_admin_role_filter(User.role))
        bug_counts = _severity_counts(bug_query.group_by(BugReport.severity).all())
        bug_counts_recent = _severity_counts(
            bug_query.filter(BugReport.created_at >= start_db, BugReport.created_at < end_exclusive_db)
            .group_by(BugReport.severity)
            .all()
        )
        return {
            "total": sum(bug_counts.values()),
            "total_last_n_days": sum(bug_counts_recent.values()),
            "by_severity": bug_counts,
            "last_n_days_by_severity": bug_counts_recent,
        }

    def _activity_counts(
        self,
        db: Session,
        *,
        scope: str,
        start_day: Optional[date] = None,
        end_day: Optional[date] = None,
    ) -> Dict[str, int]:
        query = (
            db.query(
                AggActivityDay.activity_type,
                func.sum(AggActivityDay.event_count).label("event_count"),
            )
            .filter(AggActivityDay.scope == scope)
            .group_by(AggActivityDay.activity_type)
        )
        if start_day is not None:
            query = query.filter(AggActivityDay.metric_date >= start_day)
        if end_day is not None:
            query = query.filter(AggActivityDay.metric_date <= end_day)
        return {
            str(activity_type or "").strip().lower(): int(event_count or 0)
            for activity_type, event_count in query.all()
            if activity_type is not None
        }

    def _active_conversation_count_from_runs(
        self,
        db: Session,
        *,
        include_admins: bool,
        start_db: datetime,
        end_exclusive_db: datetime,
    ) -> int:
        query = (
            db.query(func.count(func.distinct(ChatRun.conversation_id)))
            .join(Conversation, Conversation.id == ChatRun.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .filter(
                ChatRun.started_at >= start_db,
                ChatRun.started_at < end_exclusive_db,
            )
        )
        if not include_admins:
            query = query.filter(non_admin_role_filter(User.role))
        return int(query.scalar() or 0)

    def _run_outcome_metrics(
        self,
        db: Session,
        *,
        include_admins: bool,
        start_db: datetime,
        end_exclusive_db: datetime,
    ) -> Dict[str, int | float]:
        base_query = (
            db.query(ChatRun)
            .join(Conversation, Conversation.id == ChatRun.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .filter(
                ChatRun.started_at >= start_db,
                ChatRun.started_at < end_exclusive_db,
            )
        )
        if not include_admins:
            base_query = base_query.filter(non_admin_role_filter(User.role))

        total_runs = int(base_query.with_entities(func.count(ChatRun.id)).scalar() or 0)
        status_rows = (
            base_query.with_entities(
                ChatRun.status,
                func.count(ChatRun.id),
            )
            .group_by(ChatRun.status)
            .all()
        )
        status_counts = {
            str(status or "").strip().lower(): int(count or 0)
            for status, count in status_rows
            if status is not None
        }
        completed_runs = int(status_counts.get("completed", 0))
        failed_runs = int(status_counts.get("failed", 0))
        cancelled_runs = int(status_counts.get("cancelled", 0))
        failed_or_cancelled_runs = failed_runs + cancelled_runs

        failed_run = aliased(ChatRun)
        recovered_run = aliased(ChatRun)
        recovered_query = (
            db.query(func.count(failed_run.id))
            .join(Conversation, Conversation.id == failed_run.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .filter(
                failed_run.started_at >= start_db,
                failed_run.started_at < end_exclusive_db,
                failed_run.status.in_(("failed", "cancelled")),
            )
            .filter(
                db.query(recovered_run.id)
                .filter(
                    recovered_run.conversation_id == failed_run.conversation_id,
                    recovered_run.status == "completed",
                    recovered_run.started_at > func.coalesce(failed_run.finished_at, failed_run.started_at),
                    recovered_run.started_at < end_exclusive_db,
                )
                .exists()
            )
        )
        if not include_admins:
            recovered_query = recovered_query.filter(non_admin_role_filter(User.role))
        recovered_failed_or_cancelled_runs = int(recovered_query.scalar() or 0)

        return {
            "runs_started_last_n_days": total_runs,
            "runs_completed_last_n_days": completed_runs,
            "runs_failed_last_n_days": failed_runs,
            "runs_cancelled_last_n_days": cancelled_runs,
            "run_completion_rate_last_n_days": self._safe_rate(completed_runs, total_runs),
            "run_failure_rate_last_n_days": self._safe_rate(failed_runs, total_runs),
            "run_cancel_rate_last_n_days": self._safe_rate(cancelled_runs, total_runs),
            "failed_or_cancelled_runs_last_n_days": failed_or_cancelled_runs,
            "recovered_failed_or_cancelled_runs_last_n_days": recovered_failed_or_cancelled_runs,
            "failure_recovery_rate_last_n_days": self._safe_rate(
                recovered_failed_or_cancelled_runs,
                failed_or_cancelled_runs,
            ),
        }

    def _tool_diversity_metrics(
        self,
        db: Session,
        *,
        include_admins: bool,
        start_db: datetime,
        end_exclusive_db: datetime,
        active_conversation_count: int,
    ) -> Dict[str, int | float]:
        conversation_tool_rows_query = (
            db.query(
                FactAssistantTurn.conversation_id,
                func.count(
                    func.distinct(func.lower(func.trim(FactToolCall.tool_name)))
                ).label("unique_tool_count"),
            )
            .join(FactToolCall, FactToolCall.message_id == FactAssistantTurn.message_id)
            .join(Conversation, Conversation.id == FactAssistantTurn.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .filter(
                FactAssistantTurn.created_at >= start_db,
                FactAssistantTurn.created_at < end_exclusive_db,
                FactToolCall.tool_name.isnot(None),
                FactToolCall.tool_name != "",
            )
            .group_by(FactAssistantTurn.conversation_id)
        )
        if not include_admins:
            conversation_tool_rows_query = conversation_tool_rows_query.filter(non_admin_role_filter(User.role))
        conversation_tool_rows = conversation_tool_rows_query.all()

        conversations_with_any_tool = int(len(conversation_tool_rows))
        conversations_with_multi_tool = int(
            sum(
                1
                for row in conversation_tool_rows
                if int(getattr(row, "unique_tool_count", 0) or 0) >= 2
            )
        )
        total_unique_tool_counts = int(
            sum(int(getattr(row, "unique_tool_count", 0) or 0) for row in conversation_tool_rows)
        )

        unique_tools_query = (
            db.query(func.count(func.distinct(func.lower(func.trim(FactToolCall.tool_name)))))
            .join(FactAssistantTurn, FactAssistantTurn.message_id == FactToolCall.message_id)
            .join(Conversation, Conversation.id == FactAssistantTurn.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .filter(
                FactAssistantTurn.created_at >= start_db,
                FactAssistantTurn.created_at < end_exclusive_db,
                FactToolCall.tool_name.isnot(None),
                FactToolCall.tool_name != "",
            )
        )
        if not include_admins:
            unique_tools_query = unique_tools_query.filter(non_admin_role_filter(User.role))
        unique_tools_used = int(unique_tools_query.scalar() or 0)

        return {
            "unique_tools_used_last_n_days": unique_tools_used,
            "conversations_with_any_tool_last_n_days": conversations_with_any_tool,
            "conversations_with_multi_tool_last_n_days": conversations_with_multi_tool,
            "conversations_with_any_tool_rate_last_n_days": self._safe_rate(
                conversations_with_any_tool,
                active_conversation_count,
            ),
            "conversations_with_multi_tool_rate_last_n_days": self._safe_rate(
                conversations_with_multi_tool,
                active_conversation_count,
            ),
            "avg_unique_tools_per_active_conversation_last_n_days": self._safe_rate(
                total_unique_tool_counts,
                active_conversation_count,
                digits=3,
            ),
        }

    def _count_distinct_users_with_activity(
        self,
        db: Session,
        *,
        activity_type: str,
        include_admins: bool,
        start_db: datetime | None = None,
        end_exclusive_db: datetime | None = None,
    ) -> int:
        normalized_activity_type = str(activity_type or "").strip().lower()
        if not normalized_activity_type:
            return 0

        query = (
            db.query(func.count(func.distinct(UserActivity.user_id)))
            .join(User, User.id == UserActivity.user_id)
            .filter(UserActivity.activity_type == normalized_activity_type)
        )
        if start_db is not None:
            query = query.filter(UserActivity.created_at >= start_db)
        if end_exclusive_db is not None:
            query = query.filter(UserActivity.created_at < end_exclusive_db)
        if not include_admins:
            query = query.filter(non_admin_role_filter(User.role))
        return int(query.scalar() or 0)

    def _count_distinct_users_with_activity_types(
        self,
        db: Session,
        *,
        activity_types: tuple[str, ...],
        include_admins: bool,
        start_db: datetime | None = None,
        end_exclusive_db: datetime | None = None,
    ) -> int:
        normalized_types = tuple(
            value
            for value in (
                str(activity_type or "").strip().lower()
                for activity_type in activity_types
            )
            if value
        )
        if not normalized_types:
            return 0

        query = (
            db.query(func.count(func.distinct(UserActivity.user_id)))
            .join(User, User.id == UserActivity.user_id)
            .filter(UserActivity.activity_type.in_(normalized_types))
        )
        if start_db is not None:
            query = query.filter(UserActivity.created_at >= start_db)
        if end_exclusive_db is not None:
            query = query.filter(UserActivity.created_at < end_exclusive_db)
        if not include_admins:
            query = query.filter(non_admin_role_filter(User.role))
        return int(query.scalar() or 0)

    def _count_distinct_users_with_group_usage(
        self,
        db: Session,
        *,
        include_admins: bool,
        start_db: datetime,
        end_exclusive_db: datetime,
    ) -> int:
        query = (
            db.query(func.count(func.distinct(Conversation.user_id)))
            .join(ChatRun, ChatRun.conversation_id == Conversation.id)
            .join(User, User.id == Conversation.user_id)
            .filter(
                Conversation.project_id.isnot(None),
                ChatRun.started_at >= start_db,
                ChatRun.started_at < end_exclusive_db,
            )
        )
        if not include_admins:
            query = query.filter(non_admin_role_filter(User.role))
        return int(query.scalar() or 0)

    @staticmethod
    def _safe_rate(
        numerator: int,
        denominator: int,
        *,
        digits: int = 4,
    ) -> float:
        normalized_numerator = int(numerator or 0)
        normalized_denominator = int(denominator or 0)
        if normalized_denominator <= 0:
            return 0.0
        return round(float(normalized_numerator) / float(normalized_denominator), digits)

    def get_metrics(
        self,
        db: Session,
        days: int = 30,
        include_admins: bool = False,
        start_date: Optional["date"] = None,
        end_date: Optional["date"] = None,
        include_deep_metrics: bool = True,
    ) -> Dict:
        now = datetime.now(timezone.utc)
        start, end_exclusive, effective_days = _resolve_datetime_window(
            now=now,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        start_db = start
        end_exclusive_db = end_exclusive

        totals = self._feedback_counts(db, include_admins=include_admins)
        recent = self._feedback_counts(
            db,
            include_admins=include_admins,
            start_db=start_db,
            end_exclusive_db=end_exclusive_db,
        )

        helpful_rate = (totals["up"] / totals["total"]) if totals["total"] else 0.0
        helpful_rate_recent = (recent["up"] / recent["total"]) if recent["total"] else 0.0

        bug_query = db.query(BugReport.severity, func.count(BugReport.id)).join(User, User.id == BugReport.user_id)
        if not include_admins:
            bug_query = bug_query.filter(non_admin_role_filter(User.role))
        bug_counts = _severity_counts(bug_query.group_by(BugReport.severity).all())
        bug_counts_recent = _severity_counts(
            bug_query.filter(BugReport.created_at >= start_db, BugReport.created_at < end_exclusive_db)
            .group_by(BugReport.severity)
            .all()
        )
        bug_total = sum(bug_counts.values())
        bug_recent_total = sum(bug_counts_recent.values())

        usage_summary = self._usage_service.get_summary(
            db=db,
            days=effective_days,
            include_admins=include_admins,
            start_date=start_date,
            end_date=end_date,
            include_extended=False,
            include_global_totals=False,
            include_lifetime_rollups=False,
        )
        active_users = int(usage_summary.get("active_users_last_n_days", 0) or 0)
        messages_in_range = int(usage_summary.get("messages_last_n_days", 0) or 0)
        avg_response_secs = float(usage_summary.get("approx_avg_response_secs", 0.0) or 0.0)
        messages_per_active = (messages_in_range / active_users) if active_users else 0.0
        scope = "all" if include_admins else "non_admin"
        range_start_day = start.date()
        range_end_day = (end_exclusive - timedelta(days=1)).date()

        activity_totals = self._activity_counts(
            db,
            scope=scope,
        )
        activity_recent = self._activity_counts(
            db,
            scope=scope,
            start_day=range_start_day,
            end_day=range_end_day,
        )

        feature_totals = {
            "branches_created": int(activity_totals.get("conversation_branched", 0)),
            "compactions": int(activity_totals.get("conversation_compacted", 0)),
            "user_messages_submitted": int(activity_totals.get("user_message_submitted", 0)),
        }
        feature_recent = {
            "branches_created": int(activity_recent.get("conversation_branched", 0)),
            "compactions": int(activity_recent.get("conversation_compacted", 0)),
            "user_messages_submitted": int(activity_recent.get("user_message_submitted", 0)),
        }
        collaboration_totals = {
            "shares_created": int(activity_totals.get("share_created", 0)),
            "shares_imported": int(activity_totals.get("share_imported", 0)),
            "projects_created": int(activity_totals.get("project_created", 0)),
            "members_joined": int(activity_totals.get("group_joined", 0)),
        }
        collaboration_totals["collaboration_events"] = int(
            collaboration_totals["shares_created"]
            + collaboration_totals["shares_imported"]
            + collaboration_totals["projects_created"]
            + collaboration_totals["members_joined"]
        )
        collaboration_recent = {
            "shares_created": int(activity_recent.get("share_created", 0)),
            "shares_imported": int(activity_recent.get("share_imported", 0)),
            "projects_created": int(activity_recent.get("project_created", 0)),
            "members_joined": int(activity_recent.get("group_joined", 0)),
        }
        collaboration_recent["collaboration_events"] = int(
            collaboration_recent["shares_created"]
            + collaboration_recent["shares_imported"]
            + collaboration_recent["projects_created"]
            + collaboration_recent["members_joined"]
        )
        real_world_application_totals = {
            "outputs_applied_to_live_work": int(activity_totals.get("output_applied_to_live_work", 0)),
            "outputs_deployed_to_live_work": int(activity_totals.get("output_deployed_to_live_work", 0)),
        }
        real_world_application_recent = {
            "outputs_applied_to_live_work": int(activity_recent.get("output_applied_to_live_work", 0)),
            "outputs_deployed_to_live_work": int(activity_recent.get("output_deployed_to_live_work", 0)),
        }
        branch_rate_last_n_days = self._safe_rate(
            feature_recent["branches_created"],
            feature_recent["user_messages_submitted"],
        )
        users_branched_last_n_days = 0
        message_active_users_last_n_days = 0
        if include_deep_metrics:
            users_branched_last_n_days = self._count_distinct_users_with_activity(
                db,
                activity_type="conversation_branched",
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            message_active_users_last_n_days = self._count_distinct_users_with_activity(
                db,
                activity_type="user_message_submitted",
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
        users_branched_rate_last_n_days = self._safe_rate(
            users_branched_last_n_days,
            message_active_users_last_n_days,
        )

        start_day_7d = range_end_day - timedelta(days=6)
        activity_7d = self._activity_counts(
            db,
            scope=scope,
            start_day=start_day_7d,
            end_day=range_end_day,
        )
        branch_rate_7d = self._safe_rate(
            int(activity_7d.get("conversation_branched", 0)),
            int(activity_7d.get("user_message_submitted", 0)),
        )

        start_day_30d = range_end_day - timedelta(days=29)
        activity_30d = self._activity_counts(
            db,
            scope=scope,
            start_day=start_day_30d,
            end_day=range_end_day,
        )
        branch_rate_30d = self._safe_rate(
            int(activity_30d.get("conversation_branched", 0)),
            int(activity_30d.get("user_message_submitted", 0)),
        )
        active_conversations_last_n_days = 0
        run_outcomes: Dict[str, int | float] = {
            "runs_started_last_n_days": 0,
            "runs_completed_last_n_days": 0,
            "runs_failed_last_n_days": 0,
            "runs_cancelled_last_n_days": 0,
            "run_completion_rate_last_n_days": 0.0,
            "run_failure_rate_last_n_days": 0.0,
            "run_cancel_rate_last_n_days": 0.0,
            "failed_or_cancelled_runs_last_n_days": 0,
            "recovered_failed_or_cancelled_runs_last_n_days": 0,
            "failure_recovery_rate_last_n_days": 0.0,
        }
        users_with_share_activity_last_n_days = 0
        users_with_group_usage_last_n_days = 0
        users_with_output_applied_last_n_days = 0
        users_with_output_deployed_last_n_days = 0
        users_with_redaction = 0
        total_redaction_entries = int(activity_totals.get("redaction_entry_created", 0))
        if include_deep_metrics:
            active_conversations_last_n_days = self._active_conversation_count_from_runs(
                db,
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            run_outcomes = self._run_outcome_metrics(
                db,
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            users_with_share_activity_last_n_days = self._count_distinct_users_with_activity_types(
                db,
                activity_types=("share_created", "share_imported"),
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            users_with_group_usage_last_n_days = self._count_distinct_users_with_group_usage(
                db,
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            users_with_output_applied_last_n_days = self._count_distinct_users_with_activity_types(
                db,
                activity_types=("output_applied_to_live_work",),
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            users_with_output_deployed_last_n_days = self._count_distinct_users_with_activity_types(
                db,
                activity_types=("output_deployed_to_live_work",),
                include_admins=include_admins,
                start_db=start_db,
                end_exclusive_db=end_exclusive_db,
            )
            redaction_users_query = db.query(func.count(func.distinct(UserRedactionEntry.user_id))).join(
                User,
                User.id == UserRedactionEntry.user_id,
            ).filter(UserRedactionEntry.is_active.is_(True))
            redaction_entries_query = db.query(func.count(UserRedactionEntry.id)).join(
                User,
                User.id == UserRedactionEntry.user_id,
            ).filter(UserRedactionEntry.is_active.is_(True))
            if not include_admins:
                redaction_users_query = redaction_users_query.filter(non_admin_role_filter(User.role))
                redaction_entries_query = redaction_entries_query.filter(non_admin_role_filter(User.role))
            users_with_redaction = int(redaction_users_query.scalar() or 0)
            total_redaction_entries = int(redaction_entries_query.scalar() or 0)
        recent_redaction_entries = int(activity_recent.get("redaction_entry_created", 0))
        total_files_redacted = int(activity_totals.get("redaction_applied", 0))
        recent_files_redacted = int(activity_recent.get("redaction_applied", 0))

        return {
            "generated_at": now.isoformat(),
            "range_days": effective_days,
            "reporting_timezone": DEFAULT_REPORTING_TIMEZONE,
            "feedback": {
                "helpful_rate": round(helpful_rate, 4),
                "helpful_rate_last_n_days": round(helpful_rate_recent, 4),
                "totals": totals,
                "last_n_days": recent,
            },
            "bugs": {
                "total": bug_total,
                "total_last_n_days": bug_recent_total,
                "by_severity": bug_counts,
                "last_n_days_by_severity": bug_counts_recent,
            },
            "usage": {
                "active_users": active_users,
                "messages": messages_in_range,
                "avg_response_secs": round(avg_response_secs, 3),
                "messages_per_active_user": round(messages_per_active, 2),
            },
            "feature_adoption": {
                "totals": feature_totals,
                "last_n_days": feature_recent,
            },
            "collaboration": {
                "totals": collaboration_totals,
                "last_n_days": collaboration_recent,
                "users_with_share_activity_last_n_days": users_with_share_activity_last_n_days,
                "users_with_group_usage_last_n_days": users_with_group_usage_last_n_days,
                "share_activity_rate_last_n_days": self._safe_rate(
                    users_with_share_activity_last_n_days,
                    active_users,
                ),
                "group_usage_rate_last_n_days": self._safe_rate(
                    users_with_group_usage_last_n_days,
                    active_users,
                ),
                "collaboration_events_per_active_user_last_n_days": self._safe_rate(
                    collaboration_recent["collaboration_events"],
                    active_users,
                    digits=3,
                ),
            },
            "real_world_application": {
                "totals": real_world_application_totals,
                "last_n_days": real_world_application_recent,
                "users_with_output_applied_last_n_days": users_with_output_applied_last_n_days,
                "users_with_output_deployed_last_n_days": users_with_output_deployed_last_n_days,
                "output_applied_rate_last_n_days": self._safe_rate(
                    users_with_output_applied_last_n_days,
                    message_active_users_last_n_days,
                ),
                "output_deployed_rate_last_n_days": self._safe_rate(
                    users_with_output_deployed_last_n_days,
                    message_active_users_last_n_days,
                ),
                "output_deployment_conversion_last_n_days": self._safe_rate(
                    real_world_application_recent["outputs_deployed_to_live_work"],
                    real_world_application_recent["outputs_applied_to_live_work"],
                ),
            },
            "branching": {
                "branch_rate_last_n_days": branch_rate_last_n_days,
                "users_branched_last_n_days": users_branched_last_n_days,
                "message_active_users_last_n_days": message_active_users_last_n_days,
                "users_branched_rate_last_n_days": users_branched_rate_last_n_days,
                "branch_rate_7d": branch_rate_7d,
                "branch_rate_30d": branch_rate_30d,
            },
            "adaptability": (
                {
                    "active_conversations_last_n_days": active_conversations_last_n_days,
                    "avg_user_messages_per_active_conversation_last_n_days": self._safe_rate(
                        feature_recent["user_messages_submitted"],
                        active_conversations_last_n_days,
                        digits=3,
                    ),
                    **run_outcomes,
                }
                if include_deep_metrics
                else None
            ),
            "redaction": {
                "totals": {
                    "users_with_redaction": users_with_redaction,
                    "redaction_entries": total_redaction_entries,
                    "files_redacted": total_files_redacted,
                },
                "last_n_days": {
                    "redaction_entries_created": recent_redaction_entries,
                    "files_redacted": recent_files_redacted,
                },
            },
        }

    def get_time_savings_by_deliverable(
        self,
        db: Session,
        days: int = 7,
        include_admins: bool = False,
        start_date: Optional["date"] = None,
        end_date: Optional["date"] = None,
    ) -> Dict:
        now = datetime.now(timezone.utc)
        if start_date and end_date:
            series_start_day = min(start_date, end_date)
            series_end_day = max(start_date, end_date)
        else:
            series_start_day = now.date() - timedelta(days=max(0, days - 1))
            series_end_day = now.date()

        series_start_dt = datetime(series_start_day.year, series_start_day.month, series_start_day.day, tzinfo=timezone.utc)
        series_end_exclusive_dt = datetime(series_end_day.year, series_end_day.month, series_end_day.day, tzinfo=timezone.utc) + timedelta(days=1)
        totals = self._feedback_counts(db, include_admins=include_admins)
        recent = self._feedback_counts(
            db,
            include_admins=include_admins,
            start_db=series_start_dt,
            end_exclusive_db=series_end_exclusive_dt,
        )

        series_map: Dict[str, Dict[str, int]] = {}
        cursor = series_start_day
        while cursor <= series_end_day:
            series_map[cursor.strftime("%Y-%m-%d")] = {"saved": 0, "spent": 0}
            cursor += timedelta(days=1)

        scope = "all" if include_admins else "non_admin"
        daily_rows = (
            db.query(
                AggFeedbackDay.metric_date,
                AggFeedbackDay.time_saved_minutes,
                AggFeedbackDay.time_spent_minutes,
            )
            .filter(
                AggFeedbackDay.scope == scope,
                AggFeedbackDay.metric_date >= series_start_day,
                AggFeedbackDay.metric_date <= series_end_day,
            )
            .all()
        )
        for metric_day, saved, spent in daily_rows:
            if metric_day is None:
                continue
            key = metric_day.strftime("%Y-%m-%d")
            series_map[key] = {
                "saved": int(saved or 0),
                "spent": int(spent or 0),
            }

        return {
            "generated_at": now.isoformat(),
            "days": max(1, (series_end_day - series_start_day).days + 1),
            "include_admins": include_admins,
            "reporting_timezone": DEFAULT_REPORTING_TIMEZONE,
            "totals": {
                "time_saved_minutes": int(totals["time_saved_minutes"]),
                "time_spent_minutes": int(totals["time_spent_minutes"]),
            },
            "last_n_days": {
                "time_saved_minutes": int(recent["time_saved_minutes"]),
                "time_spent_minutes": int(recent["time_spent_minutes"]),
            },
            "time_series": [{"date": k, "saved": v["saved"], "spent": v["spent"]} for k, v in series_map.items()],
            "by_deliverable": [],
        }

    def get_tools_distribution_summary(
        self,
        db: Session,
        days: int = 7,
        include_admins: bool = False,
        start_date: Optional["date"] = None,
        end_date: Optional["date"] = None,
    ) -> Dict:
        now = datetime.now(timezone.utc)
        scope = "all" if include_admins else "non_admin"
        if days <= 0 and start_date is None and end_date is None:
            start_day = None
            end_day = None
            effective_days = 0
        else:
            start_dt, end_exclusive_dt, effective_days = _resolve_datetime_window(
                now=now,
                days=days,
                start_date=start_date,
                end_date=end_date,
            )
            start_day = start_dt.date()
            end_day = (end_exclusive_dt - timedelta(days=1)).date()

        query = (
            db.query(
                func.lower(func.trim(AggToolDay.tool_name)).label("tool_name"),
                func.sum(AggToolDay.call_count).label("call_count"),
                func.sum(AggToolDay.error_count).label("error_count"),
            )
            .filter(
                AggToolDay.scope == scope,
                AggToolDay.tool_name.isnot(None),
                AggToolDay.tool_name != "",
            )
            .group_by("tool_name")
            .order_by(func.sum(AggToolDay.call_count).desc())
        )
        if start_day is not None and end_day is not None:
            query = query.filter(
                AggToolDay.metric_date >= start_day,
                AggToolDay.metric_date <= end_day,
            )
        rows = query.all()

        total_calls = sum(int(row.call_count or 0) for row in rows)
        total_errors = sum(int(row.error_count or 0) for row in rows)
        tools = []
        for row in rows:
            tool_name = str(row.tool_name or "").strip().lower()
            call_count = int(row.call_count or 0)
            error_count = int(row.error_count or 0)
            percentage = (call_count / total_calls * 100.0) if total_calls > 0 else 0.0
            tools.append(
                {
                    "tool_name": tool_name,
                    "call_count": call_count,
                    "error_count": error_count,
                    "percentage": round(percentage, 2),
                }
            )
        # Compute tool diversity if we have a valid time window
        diversity = None
        if start_day is not None and end_day is not None:
            active_conversations = self._active_conversation_count_from_runs(
                db,
                include_admins=include_admins,
                start_db=start_dt,
                end_exclusive_db=end_exclusive_dt,
            )
            diversity = self._tool_diversity_metrics(
                db,
                include_admins=include_admins,
                start_db=start_dt,
                end_exclusive_db=end_exclusive_dt,
                active_conversation_count=active_conversations,
            )

        return {
            "generated_at": now.isoformat(),
            "days": effective_days,
            "include_admins": include_admins,
            "reporting_timezone": DEFAULT_REPORTING_TIMEZONE,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "tools": tools,
            "diversity": diversity,
        }
