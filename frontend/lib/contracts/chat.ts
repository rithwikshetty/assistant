import {
  type JsonRecord,
  expectRecord,
  readString,
  readNullableString,
} from "./contract-utils";
import {
  parseInteractivePendingRequestResponse,
  type InteractivePendingRequestResponse,
} from "./chat-interactive";
import {
  parseToolRequestPayloadForTool,
  parseToolResultPayloadForTool,
  type KnownToolRequestPayload,
  type KnownToolResultPayload,
} from "./chat-tool-payloads";
import {
  parseConversationContextUsage,
  parseRunUsagePayload,
  type ConversationContextUsage,
  type RunUsagePayload,
} from "./chat-usage";
import {
  parseToolArgumentsPayloadForTool,
  type KnownToolArgumentsPayload,
} from "./chat-tool-arguments";
import {
  parseToolErrorPayload,
  type ToolErrorPayload,
} from "./chat-tool-errors";

const CREATE_RUN_STATUSES = ["queued", "running"] as const;
const RUN_STATUSES = ["queued", "running", "paused", "completed", "failed", "cancelled"] as const;
const CONVERSATION_RUNTIME_STATUSES = ["queued", "idle", "running", "paused"] as const;
const TIMELINE_ITEM_TYPES = [
  "user_message",
  "assistant_message_partial",
  "assistant_message_final",
  "system_message",
] as const;
const TIMELINE_ACTORS = ["user", "assistant", "system"] as const;
const RUN_ACTIVITY_STATUSES = ["running", "completed", "failed", "cancelled"] as const;

export type CreateRunStatus = (typeof CREATE_RUN_STATUSES)[number];
export type RunStatus = (typeof RUN_STATUSES)[number];
export type ConversationRuntimeStatus = (typeof CONVERSATION_RUNTIME_STATUSES)[number];
export type TimelineItemType = (typeof TIMELINE_ITEM_TYPES)[number];
export type TimelineActor = (typeof TIMELINE_ACTORS)[number];
export type RunActivityStatus = (typeof RUN_ACTIVITY_STATUSES)[number];

export type {
  StreamContentDeltaEvent,
  StreamContentDoneEvent,
  StreamDoneEvent,
  StreamDoneStatus,
  StreamErrorEvent,
  StreamEvent,
  StreamInputRequestedEvent,
  StreamNoActiveStreamEvent,
  StreamPendingRequest,
  StreamReplayGapEvent,
  StreamRunFailedEvent,
  StreamRunStatusEvent,
  StreamRuntimeUpdateEvent,
  StreamToolCompletedEvent,
  StreamToolFailedEvent,
  StreamToolProgressEvent,
  StreamToolStartedEvent,
  StreamTransportEvent,
} from "./chat-stream-events";
export { parseStreamEvent } from "./chat-stream-events";

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  last_message_at: string;
  message_count: number;
  last_message_preview?: string | null;
  project_id?: string | null;
  parent_conversation_id?: string | null;
  branch_from_message_id?: string | null;
  archived?: boolean;
  archived_at?: string | null;
  archived_by?: string | null;
  is_pinned?: boolean;
  pinned_at?: string | null;
  owner_id: string;
  owner_name?: string | null;
  owner_email?: string | null;
  is_owner: boolean;
  can_edit: boolean;
  requires_feedback?: boolean;
  awaiting_user_input?: boolean;
  context_usage?: ConversationContextUsage | null;
}

export interface ConversationResponsePayload extends ConversationSummary {
  created_at: string;
}

export type CreateConversationResponse = ConversationResponsePayload;

export interface CreateRunResponse {
  run_id: string;
  user_message_id: string;
  status: CreateRunStatus;
  queue_position?: number;
}

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
}

export interface QueuedTurnResponse {
  queue_position: number;
  run_id: string;
  user_message_id: string;
  blocked_by_run_id?: string | null;
  created_at?: string | null;
}

export interface TimelineAttachmentPayload {
  id: string;
  original_filename?: string | null;
  filename?: string | null;
  file_type?: string | null;
  file_size?: number | null;
}

export interface TimelineMessagePayload {
  text?: string | null;
  status?: "streaming" | "pending" | "paused" | "awaiting_input" | "running" | "completed" | "failed" | "cancelled" | null;
  model_provider?: string | null;
  model_name?: string | null;
  finish_reason?: string | null;
  response_latency_ms?: number | null;
  cost_usd?: number | null;
  attachments?: TimelineAttachmentPayload[] | null;
  request_id?: string | null;
}

export interface RunActivityPayload {
  tool_call_id?: string | null;
  tool_name?: string | null;
  position?: number | null;
  arguments?: KnownToolArgumentsPayload | null;
  query?: string | null;
  result?: KnownToolResultPayload | null;
  error?: ToolErrorPayload | null;
  request?: KnownToolRequestPayload | null;
  raw_text?: string | null;
  label?: string | null;
  source?: string | null;
  item_id?: string | null;
}

export interface TimelineItem {
  id: string;
  seq: number;
  run_id?: string | null;
  type: TimelineItemType;
  actor: TimelineActor;
  created_at: string;
  role?: "user" | "assistant" | null;
  text?: string | null;
  activity_items?: RunActivityItemResponse[] | null;
  payload?: TimelineMessagePayload | null;
}

export interface TimelinePageResponse {
  items: TimelineItem[];
  has_more: boolean;
  next_cursor?: string | null;
}

export type StreamStatePendingRequestResponse = InteractivePendingRequestResponse;

export interface RunActivityItemResponse {
  id: string;
  run_id: string;
  item_key: string;
  kind: "tool" | "reasoning" | "compaction" | "user_input";
  status: RunActivityStatus;
  title?: string | null;
  summary?: string | null;
  sequence: number;
  payload: RunActivityPayload;
  created_at: string;
  updated_at: string;
}

export interface ConversationRuntimeResponse {
  conversation_id: string;
  active: boolean;
  status: ConversationRuntimeStatus;
  run_id?: string | null;
  run_message_id?: string | null;
  assistant_message_id?: string | null;
  status_label?: string | null;
  draft_text: string;
  last_seq?: number;
  resume_since_stream_event_id: number;
  activity_cursor: number;
  pending_requests: StreamStatePendingRequestResponse[];
  activity_items: RunActivityItemResponse[];
  queued_turns?: QueuedTurnResponse[];
  usage: RunUsagePayload;
  live_message?: TimelineItem | null;
}

function readEnumString<const T extends readonly string[]>(
  record: JsonRecord,
  key: string,
  label: string,
  allowedValues: T,
): T[number] {
  const value = readString(record, key, label);
  if ((allowedValues as readonly string[]).includes(value)) {
    return value as T[number];
  }
  throw new Error(`${label}.${key} must be one of: ${allowedValues.join(", ")}`);
}

function readBooleanWithDefault(record: JsonRecord, key: string, fallback: boolean): boolean {
  const value = record[key];
  if (value == null) return fallback;
  if (typeof value !== "boolean") {
    throw new Error(`${key} must be a boolean`);
  }
  return value;
}

function readNumberLike(record: JsonRecord, key: string): number | undefined {
  const value = record[key];
  if (value == null) return undefined;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  throw new Error(`${key} must be numeric`);
}

function readIntLikeWithDefault(record: JsonRecord, key: string, fallback: number): number {
  const value = readNumberLike(record, key);
  if (value == null) return fallback;
  return Math.max(0, Math.floor(value));
}

function preserveString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readNullableObject(record: JsonRecord, key: string): Record<string, unknown> | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  return expectRecord(value, key);
}

function readRecordArrayOrNull(
  record: JsonRecord,
  key: string,
): Array<Record<string, unknown>> | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  if (!Array.isArray(value)) {
    throw new Error(`${key} must be an array or null`);
  }
  return value.map((entry, index) => expectRecord(entry, `${key}[${index}]`));
}

export function parseConversationResponsePayload(raw: unknown): ConversationResponsePayload {
  const record = expectRecord(raw, "conversation");
  const contextUsageRaw = readNullableObject(record, "context_usage");

  return {
    id: readString(record, "id", "conversation"),
    title: readString(record, "title", "conversation"),
    created_at: readString(record, "created_at", "conversation"),
    updated_at: readString(record, "updated_at", "conversation"),
    last_message_at: readString(record, "last_message_at", "conversation"),
    message_count: readIntLikeWithDefault(record, "message_count", 0),
    last_message_preview: readNullableString(record, "last_message_preview"),
    project_id: readNullableString(record, "project_id"),
    parent_conversation_id: readNullableString(record, "parent_conversation_id"),
    branch_from_message_id: readNullableString(record, "branch_from_message_id"),
    archived: readBooleanWithDefault(record, "archived", false),
    archived_at: readNullableString(record, "archived_at"),
    archived_by: readNullableString(record, "archived_by"),
    is_pinned: readBooleanWithDefault(record, "is_pinned", false),
    pinned_at: readNullableString(record, "pinned_at"),
    owner_id: readString(record, "owner_id", "conversation"),
    owner_name: readNullableString(record, "owner_name"),
    owner_email: readNullableString(record, "owner_email"),
    is_owner: readBooleanWithDefault(record, "is_owner", false),
    can_edit: readBooleanWithDefault(record, "can_edit", false),
    requires_feedback: readBooleanWithDefault(record, "requires_feedback", false),
    awaiting_user_input: readBooleanWithDefault(record, "awaiting_user_input", false),
    context_usage: contextUsageRaw ? parseConversationContextUsage(contextUsageRaw, "conversation.context_usage") : null,
  };
}

export function parseConversationResponsePayloadList(raw: unknown): ConversationResponsePayload[] {
  if (!Array.isArray(raw)) {
    throw new Error("conversation list must be an array");
  }
  return raw.map((entry) => parseConversationResponsePayload(entry));
}

export function conversationResponseToSummary(
  payload: ConversationResponsePayload,
): ConversationSummary {
  const { created_at, ...summary } = payload;
  void created_at;
  return summary;
}

export function parseCreateRunResponse(raw: unknown): CreateRunResponse {
  const record = expectRecord(raw, "createRun");
  return {
    run_id: readString(record, "run_id", "createRun"),
    user_message_id: readString(record, "user_message_id", "createRun"),
    status: readEnumString(record, "status", "createRun", CREATE_RUN_STATUSES),
    queue_position: readIntLikeWithDefault(record, "queue_position", 0),
  };
}

export function parseRunStatusResponse(raw: unknown): RunStatusResponse {
  const record = expectRecord(raw, "runStatus");
  return {
    run_id: readString(record, "run_id", "runStatus"),
    status: readEnumString(record, "status", "runStatus", RUN_STATUSES),
  };
}

function parseQueuedTurnResponse(raw: unknown): QueuedTurnResponse {
  const record = expectRecord(raw, "queuedTurn");
  return {
    queue_position: readIntLikeWithDefault(record, "queue_position", 0),
    run_id: readString(record, "run_id", "queuedTurn"),
    user_message_id: readString(record, "user_message_id", "queuedTurn"),
    blocked_by_run_id: readNullableString(record, "blocked_by_run_id"),
    created_at: readNullableString(record, "created_at"),
  };
}

function parseTimelineAttachmentPayload(raw: unknown): TimelineAttachmentPayload {
  const record = expectRecord(raw, "timelineAttachment");
  return {
    id: readString(record, "id", "timelineAttachment"),
    original_filename: readNullableString(record, "original_filename"),
    filename: readNullableString(record, "filename"),
    file_type: readNullableString(record, "file_type"),
    file_size: readNumberLike(record, "file_size") ?? null,
  };
}

function parseTimelineMessagePayload(raw: unknown): TimelineMessagePayload {
  const record = expectRecord(raw, "timelinePayload");
  const statusRaw = readNullableString(record, "status");
  const allowedStatuses = [
    "streaming",
    "pending",
    "paused",
    "awaiting_input",
    "running",
    "completed",
    "failed",
    "cancelled",
  ] as const;
  const status =
    statusRaw == null
      ? statusRaw
      : (allowedStatuses as readonly string[]).includes(statusRaw)
        ? statusRaw as TimelineMessagePayload["status"]
        : (() => {
            throw new Error(`timelinePayload.status must be one of: ${allowedStatuses.join(", ")}`);
          })();
  const attachmentsRaw = readRecordArrayOrNull(record, "attachments");
  return {
    text: preserveString(record.text) ?? "",
    status,
    model_provider: readNullableString(record, "model_provider"),
    model_name: readNullableString(record, "model_name"),
    finish_reason: readNullableString(record, "finish_reason"),
    response_latency_ms: readNumberLike(record, "response_latency_ms") ?? null,
    cost_usd: readNumberLike(record, "cost_usd") ?? null,
    attachments: attachmentsRaw ? attachmentsRaw.map((entry) => parseTimelineAttachmentPayload(entry)) : null,
    request_id: readNullableString(record, "request_id"),
  };
}

function parseRunActivityPayload(raw: unknown): RunActivityPayload {
  const record = expectRecord(raw, "runActivityPayload");
  const toolName = readNullableString(record, "tool_name");
  return {
    tool_call_id: readNullableString(record, "tool_call_id"),
    tool_name: toolName,
    position: readNumberLike(record, "position") ?? null,
    arguments: (() => {
      const argumentsPayload = readNullableObject(record, "arguments");
      if (!argumentsPayload) return argumentsPayload;
      try {
        return parseToolArgumentsPayloadForTool(toolName, argumentsPayload, "runActivityPayload.arguments");
      } catch {
        return undefined;
      }
    })(),
    query: readNullableString(record, "query"),
    result: (() => {
      const result = readNullableObject(record, "result");
      if (!result) return result;
      try {
        return parseToolResultPayloadForTool(toolName, result, "runActivityPayload.result");
      } catch {
        return undefined;
      }
    })(),
    error: (() => {
      const errorPayload = readNullableObject(record, "error");
      if (!errorPayload) return errorPayload;
      try {
        return parseToolErrorPayload(errorPayload, "runActivityPayload.error");
      } catch {
        return errorPayload;
      }
    })(),
    request: (() => {
      const request = readNullableObject(record, "request");
      if (!request) return request;
      try {
        return parseToolRequestPayloadForTool(toolName, request, "runActivityPayload.request");
      } catch {
        return undefined;
      }
    })(),
    raw_text: readNullableString(record, "raw_text"),
    label: readNullableString(record, "label"),
    source: readNullableString(record, "source"),
    item_id: readNullableString(record, "item_id"),
  };
}

export function parseTimelineItem(raw: unknown): TimelineItem {
  const record = expectRecord(raw, "timelineItem");
  const roleValue = record.role;
  let role: "user" | "assistant" | null | undefined;
  if (roleValue === undefined) {
    role = undefined;
  } else if (roleValue === null) {
    role = null;
  } else if (roleValue === "user" || roleValue === "assistant") {
    role = roleValue;
  } else {
    throw new Error("timelineItem.role must be 'user', 'assistant', or null");
  }

  return {
    id: readString(record, "id", "timelineItem"),
    seq: readIntLikeWithDefault(record, "seq", 0),
    run_id: readNullableString(record, "run_id"),
    type: readEnumString(record, "type", "timelineItem", TIMELINE_ITEM_TYPES),
    actor: readEnumString(record, "actor", "timelineItem", TIMELINE_ACTORS),
    created_at: readString(record, "created_at", "timelineItem"),
    role,
    text: readNullableString(record, "text"),
    activity_items: (() => {
      const rawActivityItems = record.activity_items;
      if (!Array.isArray(rawActivityItems)) return undefined;
      return rawActivityItems.map((entry) => parseRunActivityItemResponse(entry));
    })(),
    payload: (() => {
      const payload = readNullableObject(record, "payload");
      return payload ? parseTimelineMessagePayload(payload) : null;
    })(),
  };
}

export function parseTimelinePageResponse(raw: unknown): TimelinePageResponse {
  const record = expectRecord(raw, "timelinePage");
  const itemsRaw = record.items;
  if (!Array.isArray(itemsRaw)) {
    throw new Error("timelinePage.items must be an array");
  }

  return {
    items: itemsRaw.map((item) => parseTimelineItem(item)),
    has_more: readBooleanWithDefault(record, "has_more", false),
    next_cursor: readNullableString(record, "next_cursor"),
  };
}

function parseStreamStatePendingRequest(raw: unknown): InteractivePendingRequestResponse {
  return parseInteractivePendingRequestResponse(raw, "streamStatePendingRequest");
}

function parseRunActivityItemResponse(raw: unknown): RunActivityItemResponse {
  const record = expectRecord(raw, "runActivityItem");
  const kind = readString(record, "kind", "runActivityItem");
  if (!["tool", "reasoning", "compaction", "user_input"].includes(kind)) {
    throw new Error("runActivityItem.kind must be a valid activity kind");
  }
  return {
    id: readString(record, "id", "runActivityItem"),
    run_id: readString(record, "run_id", "runActivityItem"),
    item_key: readString(record, "item_key", "runActivityItem"),
    kind: kind as RunActivityItemResponse["kind"],
    status: readEnumString(record, "status", "runActivityItem", RUN_ACTIVITY_STATUSES),
    title: readNullableString(record, "title"),
    summary: readNullableString(record, "summary"),
    sequence: readIntLikeWithDefault(record, "sequence", 0),
    payload: (() => {
      const payload = readNullableObject(record, "payload");
      return payload ? parseRunActivityPayload(payload) : {};
    })(),
    created_at: readString(record, "created_at", "runActivityItem"),
    updated_at: readString(record, "updated_at", "runActivityItem"),
  };
}

export function parseConversationRuntimeResponse(raw: unknown): ConversationRuntimeResponse {
  const record = expectRecord(raw, "conversationRuntime");
  const pendingRequestsRaw = record.pending_requests;
  const pendingRequests = Array.isArray(pendingRequestsRaw)
    ? pendingRequestsRaw.map((entry) => parseStreamStatePendingRequest(entry))
    : [];
  const activityItemsRaw = Array.isArray(record.activity_items)
    ? record.activity_items
    : [];
  const activityItems = Array.isArray(activityItemsRaw)
    ? activityItemsRaw.map((entry) => parseRunActivityItemResponse(entry))
    : [];
  const draftText = readNullableString(record, "draft_text");
  const queuedTurnsRaw = readRecordArrayOrNull(record, "queued_turns") ?? [];
  const queuedTurns = queuedTurnsRaw.map((entry) => parseQueuedTurnResponse(entry));
  const usageRaw = readNullableObject(record, "usage") ?? {};
  const usage = parseRunUsagePayload(usageRaw, "conversationRuntime.usage");
  const liveMessageRaw = record.live_message;
  const liveMessage =
    liveMessageRaw && typeof liveMessageRaw === "object" && !Array.isArray(liveMessageRaw)
      ? parseTimelineItem(liveMessageRaw)
      : null;
  const statusLabel = readNullableString(record, "status_label");
  const resumeSinceStreamEventId = readIntLikeWithDefault(record, "resume_since_stream_event_id", 0);
  const activityCursor = readIntLikeWithDefault(record, "activity_cursor", resumeSinceStreamEventId);

  return {
    conversation_id: readString(record, "conversation_id", "conversationRuntime"),
    active: readBooleanWithDefault(record, "active", false),
    status: readEnumString(record, "status", "conversationRuntime", CONVERSATION_RUNTIME_STATUSES),
    run_id: readNullableString(record, "run_id"),
    run_message_id: readNullableString(record, "run_message_id"),
    assistant_message_id: readNullableString(record, "assistant_message_id"),
    status_label: statusLabel,
    draft_text: typeof draftText === "string" ? draftText : "",
    last_seq: readIntLikeWithDefault(record, "last_seq", 0),
    resume_since_stream_event_id: resumeSinceStreamEventId,
    activity_cursor: activityCursor,
    pending_requests: pendingRequests,
    activity_items: activityItems,
    queued_turns: queuedTurns,
    usage,
    live_message: liveMessage,
  };
}

export type { ConversationContextUsage, RunUsagePayload } from "./chat-usage";
