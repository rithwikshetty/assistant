from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class CountItem(BaseModel):
    date: str
    count: int


class MessagesByDay(BaseModel):
    date: str
    total: int
    user: int
    assistant: int


class FileTypeBreakdown(BaseModel):
    file_type: str
    count: int
    size_bytes: int


class TopUserItem(BaseModel):
    user_id: str
    email: str
    count: int
    size_bytes: Optional[int] = None


class MessageUsageSnapshot(BaseModel):
    message_count: int = 0
    effective_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    avg_response_latency_ms: Optional[float] = None
    avg_tool_calls: Optional[float] = None
    cost_usd: float = 0.0


class ModelUsageSnapshot(BaseModel):
    model: str
    source: Literal["chat", "non_chat", "mixed"] = "chat"
    processes: List[str] = Field(default_factory=list)
    message_count: int = 0
    effective_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    avg_response_latency_ms: Optional[float] = None
    cost_usd: float = 0.0


class ModelCostByDay(BaseModel):
    date: str
    total: float = 0.0
    models: Dict[str, float] = Field(default_factory=dict)


class UsageSummary(BaseModel):
    generated_at: str
    range_start: str
    range_end: str
    days: int
    reporting_timezone: str = "UTC"

    # Totals
    total_users: int
    total_conversations: int
    total_messages: int
    total_files: int
    total_storage_bytes: int

    # Last N days
    messages_last_n_days: int
    file_uploads_last_n_days: int

    # Series (last 14 days)
    users_per_day: List[CountItem]
    conversations_per_day: List[CountItem]
    messages_per_day: List[MessagesByDay]
    file_uploads_per_day: List[CountItem]
    active_users_per_day: List[CountItem]

    # Breakdowns
    files_by_type: List[FileTypeBreakdown]
    users_by_department: List[TopUserItem]

    # Leaderboards
    top_users_by_messages: List[TopUserItem]
    top_uploaders: List[TopUserItem]

    # Quality/latency (approx)
    approx_avg_response_secs: float

    assistant_usage_last_n_days: MessageUsageSnapshot
    assistant_usage_lifetime: MessageUsageSnapshot
    model_usage_last_n_days: List[ModelUsageSnapshot]
    model_usage_chat_last_n_days: List[ModelUsageSnapshot] = Field(default_factory=list)
    model_usage_non_chat_last_n_days: List[ModelUsageSnapshot] = Field(default_factory=list)
    assistant_cost_last_n_days: float
    non_chat_cost_last_n_days: float = 0.0
    total_model_cost_last_n_days: float = 0.0
    model_cost_timeseries: List[ModelCostByDay]
    model_cost_timeseries_chat: List[ModelCostByDay] = Field(default_factory=list)
    model_cost_timeseries_non_chat: List[ModelCostByDay] = Field(default_factory=list)
