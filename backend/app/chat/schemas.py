"""Pydantic schemas for chat endpoints."""
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from typing import Annotated, List, Optional, Dict, Set, Any, Literal, Union


ChatTimelineItemType = Literal[
    "user_message",
    "assistant_message_partial",
    "assistant_message_final",
    "system_message",
]
ChatTimelineActor = Literal["user", "assistant", "system"]
CreateRunStatus = Literal["queued", "running"]
ChatRunStatus = Literal["queued", "idle", "running", "paused", "completed", "failed", "cancelled"]
ConversationRuntimeStatus = Literal["queued", "idle", "running", "paused"]
RunActivityStatus = Literal["running", "completed", "failed", "cancelled"]
ChatMessageStatus = Literal["streaming", "pending", "paused", "awaiting_input", "running", "completed", "failed", "cancelled"]
InteractiveToolType = Literal["user_input"]
ChartToolType = Literal["bar", "line", "pie", "area", "stacked_bar", "waterfall"]
GanttViewMode = Literal["Day", "Week", "Month", "Year"]
TaskToolAction = Literal["list", "get", "create", "update", "complete", "delete", "comment"]
TaskToolStatus = Literal["todo", "in_progress", "done"]
TaskToolPriority = Literal["low", "medium", "high", "urgent"]
TaskToolView = Literal["active", "completed", "all"]
TaskToolScope = Literal["all", "created", "assigned"]
class ConversationContextUsageResponse(BaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    current_context_tokens: Optional[int] = None
    peak_context_tokens: Optional[int] = None
    max_context_tokens: Optional[int] = None
    remaining_context_tokens: Optional[int] = None
    aggregated_input_tokens: Optional[int] = None
    aggregated_output_tokens: Optional[int] = None
    aggregated_total_tokens: Optional[int] = None
    cumulative_input_tokens: Optional[int] = None
    cumulative_output_tokens: Optional[int] = None
    cumulative_total_tokens: Optional[int] = None
    compact_trigger_tokens: Optional[int] = None
    source: Optional[str] = None


class RunUsagePayloadResponse(BaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    base_input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    max_context_tokens: Optional[int] = None
    remaining_context_tokens: Optional[int] = None
    aggregated_input_tokens: Optional[int] = None
    aggregated_output_tokens: Optional[int] = None
    aggregated_total_tokens: Optional[int] = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    last_message_at: str
    message_count: int
    project_id: Optional[str] = None
    parent_conversation_id: Optional[str] = None
    branch_from_message_id: Optional[str] = None
    archived: bool = False
    archived_at: Optional[str] = None
    archived_by: Optional[str] = None
    is_pinned: bool = False
    pinned_at: Optional[str] = None
    owner_id: str
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    is_owner: bool = False
    can_edit: bool = False
    requires_feedback: bool = False
    awaiting_user_input: bool = False
    context_usage: Optional[ConversationContextUsageResponse] = None


class MessageCreate(BaseModel):
    content: str
    # Optional idempotency key for the user message in this request
    request_id: Optional[str] = None
    attachments: Optional[List[str]] = None


class BranchConversationRequest(BaseModel):
    message_id: str


class CreateConversationRequest(BaseModel):
    request_id: Optional[str] = None
    project_id: Optional[str] = None
    title: Optional[str] = None
    conversation_id: Optional[str] = None

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("conversation_id cannot be empty")
        try:
            UUID(cleaned)
        except ValueError as exc:
            raise ValueError("conversation_id must be a valid UUID") from exc
        return cleaned


class TitleUpdateRequest(BaseModel):
    title: str


class TitleResponse(BaseModel):
    title: str
    conversation_id: str
    updated_at: str
    generated_at: str


class ProjectAssignmentRequest(BaseModel):
    project_id: Optional[str] = None

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("project_id cannot be empty")
        return cleaned


class BulkArchiveRequest(BaseModel):
    conversation_ids: List[str] = Field(..., min_length=1, max_length=50)

    @field_validator("conversation_ids")
    @classmethod
    def validate_conversation_ids(cls, value: List[str]) -> List[str]:
        """Ensure IDs are non-empty strings and remove duplicates while preserving order."""
        if not value:
            raise ValueError("conversation_ids must contain at least one item")

        cleaned: List[str] = []
        seen: Set[str] = set()
        for raw in value:
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise ValueError("conversation_ids must be strings")
            item = raw.strip()
            if not item:
                continue
            if item in seen:
                continue
            seen.add(item)
            cleaned.append(item)

        if not cleaned:
            raise ValueError("conversation_ids must contain at least one valid ID")

        return cleaned


class BulkArchiveResponse(BaseModel):
    archived_ids: List[str]
    already_archived_ids: List[str]
    not_found_ids: List[str]
    archived_timestamps: Dict[str, str] = {}


class CreateRunRequest(BaseModel):
    text: str
    attachment_ids: Optional[List[str]] = None
    request_id: Optional[str] = None


class CreateRunResponse(BaseModel):
    run_id: str
    user_message_id: str
    status: CreateRunStatus
    queue_position: int = 0


class UserInputQuestionOptionPayload(BaseModel):
    label: str
    description: str


class UserInputQuestionPayload(BaseModel):
    id: str
    question: str
    options: List[UserInputQuestionOptionPayload] = Field(..., min_length=2)


class RequestUserInputRequestPayload(BaseModel):
    tool: Literal["request_user_input"]
    title: str
    prompt: str
    questions: List[UserInputQuestionPayload] = Field(..., min_length=1, max_length=4)
    custom_input_label: Optional[str] = None
    submit_label: Optional[str] = None


class UserInputAnswerPayload(BaseModel):
    question_id: str
    option_label: str


class RequestUserInputSubmissionPayload(BaseModel):
    answers: List[UserInputAnswerPayload] = Field(default_factory=list)
    custom_response: Optional[str] = None


class RequestUserInputPendingResultPayload(BaseModel):
    status: Literal["pending"]
    interaction_type: InteractiveToolType
    request: RequestUserInputRequestPayload


class RequestUserInputCompletedResultPayload(BaseModel):
    status: Literal["completed"]
    interaction_type: InteractiveToolType
    request: RequestUserInputRequestPayload
    answers: List[UserInputAnswerPayload] = Field(default_factory=list)
    custom_response: Optional[str] = None


class QueryToolArgumentsResponse(BaseModel):
    query: str


class RetrievalProjectFilesToolArgumentsResponse(BaseModel):
    query: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=25)


class FileReadToolArgumentsResponse(BaseModel):
    file_id: str
    start: Optional[int] = Field(default=None, ge=0)
    length: Optional[int] = Field(default=None, ge=1)
    full: Optional[bool] = None


class TasksToolArgumentsResponse(BaseModel):
    action: Optional[TaskToolAction] = None
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskToolStatus] = None
    priority: Optional[TaskToolPriority] = None
    due_at: Optional[str] = None
    category: Optional[str] = None
    conversation_id: Optional[str] = None
    assignee_ids: List[str] = Field(default_factory=list)
    assignee_emails: List[str] = Field(default_factory=list)
    content: Optional[str] = None
    view: Optional[TaskToolView] = None
    scope: Optional[TaskToolScope] = None
    due_from: Optional[str] = None
    due_to: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=200)


class LoadSkillToolArgumentsResponse(BaseModel):
    skill_id: str


class ChartToolArgumentsResponse(BaseModel):
    type: ChartToolType
    title: str
    data: List[Dict[str, Union[str, int, float, bool]]] = Field(..., min_length=1)
    x_axis_key: Optional[str] = None
    data_keys: List[str] = Field(default_factory=list)
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None
    colors: List[str] = Field(default_factory=list)


class GanttTaskToolArgumentsResponse(BaseModel):
    id: str
    name: str
    start: str
    end: str
    progress: Optional[float] = None
    dependencies: Optional[str] = None
    custom_bar_color: Optional[str] = None


class GanttToolArgumentsResponse(BaseModel):
    title: str
    tasks: List[GanttTaskToolArgumentsResponse] = Field(..., min_length=1)
    view_mode: Optional[GanttViewMode] = None
    readonly: Optional[bool] = None


class RequestUserInputToolArgumentsResponse(BaseModel):
    title: str
    prompt: str
    questions: List[UserInputQuestionPayload] = Field(..., min_length=1, max_length=4)
    submit_label: Optional[str] = None


class ExecuteCodeToolArgumentsResponse(BaseModel):
    code: str
    file_ids: List[str] = Field(default_factory=list)
    skill_assets: List[str] = Field(default_factory=list)
    timeout: Optional[int] = Field(default=None, ge=5, le=120)


class ChartToolConfigPayloadResponse(BaseModel):
    x_axis_key: Optional[str] = None
    data_keys: Optional[List[str]] = None
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None
    colors: Optional[List[str]] = None


class ChartToolAutoRetryPayloadResponse(BaseModel):
    attempted: bool
    reason: Literal["sparse_data"]
    original_points: int
    filtered_points: int


class ChartToolResultPayloadResponse(BaseModel):
    type: ChartToolType
    title: str
    data: List[Dict[str, Any]] = Field(..., min_length=1)
    config: Optional[ChartToolConfigPayloadResponse] = None
    auto_retry: Optional[ChartToolAutoRetryPayloadResponse] = None


class GanttTaskPayloadResponse(BaseModel):
    id: str
    name: str
    start: str
    end: str
    progress: Optional[float] = None
    dependencies: Optional[str] = None
    custom_bar_color: Optional[str] = None


class GanttToolResultPayloadResponse(BaseModel):
    title: str
    tasks: List[GanttTaskPayloadResponse] = Field(..., min_length=1)
    view_mode: Optional[GanttViewMode] = None
    readonly: Optional[bool] = None


class WebSearchCitationPayloadResponse(BaseModel):
    index: Optional[int] = None
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    published_at: Optional[str] = None
    updated_at: Optional[str] = None


class WebSearchResultPayloadResponse(BaseModel):
    content: str
    citations: List[WebSearchCitationPayloadResponse] = Field(default_factory=list)


class KnowledgeSourcePayloadResponse(BaseModel):
    content: Optional[str] = None
    score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeProjectFileResultPayloadResponse(BaseModel):
    file_id: Optional[str] = None
    filename: Optional[str] = None
    excerpts: List[str] = Field(default_factory=list)
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    match_count: Optional[int] = None
    filename_match: Optional[bool] = None


class KnowledgeResultPayloadResponse(BaseModel):
    content: Optional[str] = None
    message: Optional[str] = None
    sources: List[KnowledgeSourcePayloadResponse] = Field(default_factory=list)
    files: List[str] = Field(default_factory=list)
    results: List[KnowledgeProjectFileResultPayloadResponse] = Field(default_factory=list)
    total_nodes: Optional[int] = None
    query: Optional[str] = None
    error: Optional[str] = None


class CalculationInputPayloadResponse(BaseModel):
    label: Optional[str] = None
    value: Optional[float] = None
    display: Optional[str] = None


class CalculationValuePayloadResponse(BaseModel):
    label: Optional[str] = None
    value: Optional[float] = None
    display: Optional[str] = None


class CalculationDetailPayloadResponse(BaseModel):
    label: Optional[str] = None
    value: Optional[str] = None


class CalculationResultPayloadResponse(BaseModel):
    operation: Optional[str] = None
    operation_label: Optional[str] = None
    precision: Optional[float] = None
    inputs: Dict[str, CalculationInputPayloadResponse] = Field(default_factory=dict)
    result: Optional[CalculationValuePayloadResponse] = None
    explanation: Optional[str] = None
    reasoning: Optional[str] = None
    details: List[CalculationDetailPayloadResponse] = Field(default_factory=list)
    error: Optional[str] = None


class TaskAssigneePayloadResponse(BaseModel):
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    assigned_by_id: Optional[str] = None
    seen_at: Optional[str] = None


class TaskItemPayloadResponse(BaseModel):
    id: Optional[str] = None
    created_by_id: Optional[str] = None
    category: Optional[str] = None
    conversation_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[str] = None
    completed_at: Optional[str] = None
    is_archived: Optional[bool] = None
    archived_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    assignees: List[TaskAssigneePayloadResponse] = Field(default_factory=list)
    is_assigned_to_me: Optional[bool] = None
    is_unseen_for_me: Optional[bool] = None


class TaskCommentPayloadResponse(BaseModel):
    id: Optional[str] = None
    task_id: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    content: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TasksResultPayloadResponse(BaseModel):
    action: Optional[str] = None
    task: Optional[TaskItemPayloadResponse] = None
    items: List[TaskItemPayloadResponse] = Field(default_factory=list)
    count: Optional[int] = None
    comment: Optional[TaskCommentPayloadResponse] = None
    comments: List[TaskCommentPayloadResponse] = Field(default_factory=list)
    message: Optional[str] = None
    query: Optional[str] = None
    results: List[KnowledgeProjectFileResultPayloadResponse] = Field(default_factory=list)
    error: Optional[str] = None


class FileReadChunkPayloadResponse(BaseModel):
    content: Optional[str] = None
    chunk_start: Optional[int] = None
    chunk_end: Optional[int] = None


class FileReadContentBlockPayloadResponse(BaseModel):
    type: Optional[str] = None
    text: Optional[str] = None
    source: Optional[Dict[str, Any]] = None


class FileReadResultPayloadResponse(BaseModel):
    file_id: Optional[str] = None
    filename: Optional[str] = None
    original_filename: Optional[str] = None
    file_type: Optional[str] = None
    chunks: List[FileReadChunkPayloadResponse] = Field(default_factory=list)
    total_length: Optional[int] = None
    has_more: Optional[bool] = None
    is_truncated: Optional[bool] = None
    content: Optional[str] = None
    note: Optional[str] = None
    has_embedded_images: Optional[bool] = None
    embedded_image_count: Optional[int] = None
    content_blocks: List[FileReadContentBlockPayloadResponse] = Field(
        default_factory=list,
        alias="_content_blocks",
    )
    error: Optional[str] = None


class ExecuteCodeGeneratedFilePayloadResponse(BaseModel):
    file_id: Optional[str] = None
    filename: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    download_url: Optional[str] = None
    download_path: Optional[str] = None


class ExecuteCodeResultPayloadResponse(BaseModel):
    code: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    execution_time_ms: Optional[int] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    generated_files: List[ExecuteCodeGeneratedFilePayloadResponse] = Field(default_factory=list)
    retries_used: Optional[int] = None


class SkillResultPayloadResponse(BaseModel):
    skill_id: Optional[str] = None
    title: Optional[str] = None
    name: Optional[str] = None
    content: Optional[str] = None
    is_module: Optional[bool] = None
    has_modules: Optional[bool] = None
    available_modules: List[str] = Field(default_factory=list)
    parent_skill: Optional[str] = None
    note: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None


class ToolErrorPayloadResponse(BaseModel):
    message: Optional[str] = None
    code: Optional[str] = None


class RequestUserInputPendingRequestResponse(BaseModel):
    call_id: str
    tool_name: Literal["request_user_input"]
    request: RequestUserInputRequestPayload
    result: RequestUserInputPendingResultPayload


StreamStatePendingRequest = Annotated[
    RequestUserInputPendingRequestResponse,
    Field(discriminator="tool_name"),
]


class SubmitRunUserInputRequest(BaseModel):
    tool_call_id: Optional[str] = None
    result: RequestUserInputSubmissionPayload


class SubmitRunUserInputResponse(BaseModel):
    run_id: str
    status: Literal["running"]


class CancelRunResponse(BaseModel):
    run_id: str
    status: ChatRunStatus


class QueuedTurnResponse(BaseModel):
    queue_position: int
    run_id: str
    user_message_id: str
    blocked_by_run_id: Optional[str] = None
    created_at: Optional[str] = None


class TimelineAttachmentResponse(BaseModel):
    id: str
    original_filename: Optional[str] = None
    filename: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None


class TimelineMessagePayloadResponse(BaseModel):
    text: str = ""
    status: Optional[ChatMessageStatus] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    finish_reason: Optional[str] = None
    response_latency_ms: Optional[int] = None
    cost_usd: Optional[float] = None
    attachments: Optional[List[TimelineAttachmentResponse]] = None
    request_id: Optional[str] = None


class RunActivityPayloadResponse(BaseModel):
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    position: Optional[int] = None
    arguments: Optional[
        Union[
            QueryToolArgumentsResponse,
            RetrievalProjectFilesToolArgumentsResponse,
            FileReadToolArgumentsResponse,
            TasksToolArgumentsResponse,
            LoadSkillToolArgumentsResponse,
            ChartToolArgumentsResponse,
            GanttToolArgumentsResponse,
            RequestUserInputToolArgumentsResponse,
            ExecuteCodeToolArgumentsResponse,
        ]
    ] = None
    query: Optional[str] = None
    result: Optional[
        Union[
            RequestUserInputPendingResultPayload,
            RequestUserInputCompletedResultPayload,
            ChartToolResultPayloadResponse,
            GanttToolResultPayloadResponse,
            WebSearchResultPayloadResponse,
            KnowledgeResultPayloadResponse,
            CalculationResultPayloadResponse,
            TasksResultPayloadResponse,
            FileReadResultPayloadResponse,
            ExecuteCodeResultPayloadResponse,
            SkillResultPayloadResponse,
        ]
    ] = None
    error: Optional[ToolErrorPayloadResponse] = None
    request: Optional[
        Union[
            RequestUserInputRequestPayload,
        ]
    ] = None
    raw_text: Optional[str] = None
    label: Optional[str] = None
    source: Optional[str] = None
    item_id: Optional[str] = None


class RunActivityItemResponse(BaseModel):
    id: str
    run_id: str
    item_key: str
    kind: Literal["tool", "reasoning", "compaction", "user_input"]
    status: RunActivityStatus
    title: Optional[str] = None
    summary: Optional[str] = None
    sequence: int
    payload: RunActivityPayloadResponse = Field(default_factory=RunActivityPayloadResponse)
    created_at: str
    updated_at: str


class TimelineItemResponse(BaseModel):
    id: str
    seq: int
    run_id: Optional[str] = None
    type: ChatTimelineItemType
    actor: ChatTimelineActor
    created_at: str
    role: Optional[str] = None
    text: Optional[str] = None
    activity_items: Optional[List[RunActivityItemResponse]] = None
    payload: TimelineMessagePayloadResponse = Field(default_factory=TimelineMessagePayloadResponse)


class TimelinePageResponse(BaseModel):
    items: List[TimelineItemResponse]
    has_more: bool
    next_cursor: Optional[str] = None


class ConversationRuntimeResponse(BaseModel):
    conversation_id: str
    active: bool
    status: ConversationRuntimeStatus
    run_id: Optional[str] = None
    run_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    status_label: Optional[str] = None
    draft_text: str = ""
    last_seq: int = 0
    resume_since_stream_event_id: int = 0
    activity_cursor: int = 0
    pending_requests: List[StreamStatePendingRequest] = Field(default_factory=list)
    activity_items: List[RunActivityItemResponse] = Field(default_factory=list)
    queued_turns: List[QueuedTurnResponse] = Field(default_factory=list)
    usage: RunUsagePayloadResponse = Field(default_factory=RunUsagePayloadResponse)
    live_message: Optional[TimelineItemResponse] = None


class MessageSuggestionsResponse(BaseModel):
    message_id: str
    suggestions: List[str]
