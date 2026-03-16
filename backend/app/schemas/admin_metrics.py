from typing import Dict

from pydantic import BaseModel, Field


class FeedbackCounts(BaseModel):
    total: int = Field(0, description="Total feedback count")
    up: int = Field(0, description="Positive feedback count")
    down: int = Field(0, description="Negative feedback count")
    time_saved_minutes: int = Field(0, description="Sum of time saved minutes (thumbs up)")
    time_spent_minutes: int = Field(0, description="Sum of time lost/spent minutes (thumbs down)")


class FeedbackMetrics(BaseModel):
    helpful_rate: float = Field(0.0, description="Overall helpful feedback rate (0-1)")
    helpful_rate_last_n_days: float = Field(
        0.0, description="Helpful feedback rate for the configured range"
    )
    totals: FeedbackCounts
    last_n_days: FeedbackCounts


class BugMetrics(BaseModel):
    total: int = Field(0, description="Total bug reports")
    total_last_n_days: int = Field(0, description="Bug reports in range")
    by_severity: Dict[str, int]
    last_n_days_by_severity: Dict[str, int]


class UsageSnapshot(BaseModel):
    active_users: int = 0
    messages: int = 0
    avg_response_secs: float = 0.0
    messages_per_active_user: float = 0.0


class FeatureAdoptionCounts(BaseModel):
    branches_created: int = 0
    compactions: int = 0
    user_messages_submitted: int = 0


class FeatureAdoptionMetrics(BaseModel):
    totals: FeatureAdoptionCounts
    last_n_days: FeatureAdoptionCounts


class CollaborationCounts(BaseModel):
    shares_created: int = 0
    shares_imported: int = 0
    projects_created: int = 0
    members_joined: int = 0
    collaboration_events: int = 0


class CollaborationMetrics(BaseModel):
    totals: CollaborationCounts
    last_n_days: CollaborationCounts
    users_with_share_activity_last_n_days: int = 0
    users_with_group_usage_last_n_days: int = 0
    share_activity_rate_last_n_days: float = 0.0
    group_usage_rate_last_n_days: float = 0.0
    collaboration_events_per_active_user_last_n_days: float = 0.0


class RealWorldApplicationCounts(BaseModel):
    outputs_applied_to_live_work: int = 0
    outputs_deployed_to_live_work: int = 0


class RealWorldApplicationMetrics(BaseModel):
    totals: RealWorldApplicationCounts
    last_n_days: RealWorldApplicationCounts
    users_with_output_applied_last_n_days: int = 0
    users_with_output_deployed_last_n_days: int = 0
    output_applied_rate_last_n_days: float = 0.0
    output_deployed_rate_last_n_days: float = 0.0
    output_deployment_conversion_last_n_days: float = 0.0


class BranchingMetrics(BaseModel):
    branch_rate_last_n_days: float = 0.0
    users_branched_last_n_days: int = 0
    message_active_users_last_n_days: int = 0
    users_branched_rate_last_n_days: float = 0.0
    branch_rate_7d: float = 0.0
    branch_rate_30d: float = 0.0


class AdaptabilityMetrics(BaseModel):
    active_conversations_last_n_days: int = 0
    avg_user_messages_per_active_conversation_last_n_days: float = 0.0
    runs_started_last_n_days: int = 0
    runs_completed_last_n_days: int = 0
    runs_failed_last_n_days: int = 0
    runs_cancelled_last_n_days: int = 0
    run_completion_rate_last_n_days: float = 0.0
    run_failure_rate_last_n_days: float = 0.0
    run_cancel_rate_last_n_days: float = 0.0
    failed_or_cancelled_runs_last_n_days: int = 0
    recovered_failed_or_cancelled_runs_last_n_days: int = 0
    failure_recovery_rate_last_n_days: float = 0.0


class ToolDiversityMetrics(BaseModel):
    unique_tools_used_last_n_days: int = 0
    conversations_with_any_tool_last_n_days: int = 0
    conversations_with_multi_tool_last_n_days: int = 0
    conversations_with_any_tool_rate_last_n_days: float = 0.0
    conversations_with_multi_tool_rate_last_n_days: float = 0.0
    avg_unique_tools_per_active_conversation_last_n_days: float = 0.0


class RedactionTotals(BaseModel):
    users_with_redaction: int = 0
    redaction_entries: int = 0
    files_redacted: int = 0


class RedactionLastNDays(BaseModel):
    redaction_entries_created: int = 0
    files_redacted: int = 0


class RedactionMetrics(BaseModel):
    totals: RedactionTotals
    last_n_days: RedactionLastNDays


class MetricsSummary(BaseModel):
    generated_at: str
    range_days: int
    reporting_timezone: str = "UTC"
    feedback: FeedbackMetrics
    bugs: BugMetrics
    usage: UsageSnapshot
    feature_adoption: FeatureAdoptionMetrics | None = None
    collaboration: CollaborationMetrics | None = None
    real_world_application: RealWorldApplicationMetrics | None = None
    branching: BranchingMetrics | None = None
    adaptability: AdaptabilityMetrics | None = None
    redaction: RedactionMetrics | None = None


# Time savings by deliverable schemas
class TimeTotals(BaseModel):
    time_saved_minutes: int = 0
    time_spent_minutes: int = 0


class DeliverableTimeSavings(BaseModel):
    deliverable: str
    saved_minutes: int
    spent_minutes: int
    saved_recent: int
    spent_recent: int


class TimeSeriesPoint(BaseModel):
    date: str
    saved: int
    spent: int


class TimeSavingsInsights(BaseModel):
    generated_at: str
    days: int
    include_admins: bool
    reporting_timezone: str = "UTC"
    totals: TimeTotals
    last_n_days: TimeTotals
    time_series: list[TimeSeriesPoint]
    by_deliverable: list[DeliverableTimeSavings]


# Overview dashboard schemas (optimized single-call endpoint)
class CountByDay(BaseModel):
    date: str
    count: int


class MessagesByDay(BaseModel):
    date: str
    total: int
    user: int
    assistant: int


class OverviewTodayStats(BaseModel):
    active_users: int = 0
    conversations: int = 0
    spend_usd: float = 0.0
    time_saved_minutes: int = 0
    time_lost_minutes: int = 0


class OverviewLifetimeStats(BaseModel):
    helpful_rate: float = 0.0
    total_ratings: int = 0


class OverviewSummary(BaseModel):
    generated_at: str
    days: int
    include_admins: bool
    reporting_timezone: str = "UTC"
    today: OverviewTodayStats
    lifetime: OverviewLifetimeStats
    conversations_per_day: list[CountByDay]
    messages_per_day: list[MessagesByDay]


# Tools distribution schemas
class ToolDistributionItem(BaseModel):
    tool_name: str
    call_count: int
    error_count: int
    percentage: float = Field(0.0, description="Percentage of total calls")


class ToolsDistributionSummary(BaseModel):
    generated_at: str
    days: int
    include_admins: bool = False
    reporting_timezone: str = "UTC"
    total_calls: int
    total_errors: int
    tools: list[ToolDistributionItem]
    diversity: ToolDiversityMetrics | None = None


class SectorDistributionItem(BaseModel):
    sector: str
    conversation_count: int
    percentage: float = Field(0.0, description="Percentage of active conversations in range")


class SectorDistributionSummary(BaseModel):
    generated_at: str
    reporting_timezone: str = "UTC"
    start_date: str
    end_date: str
    include_admins: bool = False
    total_conversations: int = 0
    sectors: list[SectorDistributionItem] = Field(default_factory=list)
