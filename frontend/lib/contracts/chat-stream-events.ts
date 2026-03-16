import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import { type JsonRecord, isRecord } from "./contract-utils";
import {
  isChatStreamEventType,
  isChatToolName,
  type ChatToolName,
} from "@/lib/chat/generated/ws-contract";
import {
  parseInteractivePendingRequestTransport,
  type InteractivePendingRequestTransport,
} from "./chat-interactive";
import {
  parseToolResultPayloadForTool,
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

type StreamTransportEventBase<TType extends string, TData> = {
  id: number;
  type: TType;
  data: TData;
};

export type StreamPendingRequest = InteractivePendingRequestTransport;

export type StreamDoneStatus = "completed" | "paused" | "cancelled" | "failed";

export type StreamReplayGapEvent = StreamTransportEventBase<"replay_gap", {
  expectedNextStreamEventId: number;
  resumedAtStreamEventId: number;
}>;

export type StreamNoActiveStreamEvent = StreamTransportEventBase<"no_active_stream", {
  reason: string | null;
  conversationId: string | null;
  runMessageId: string | null;
}>;

export type StreamRunStatusEvent = StreamTransportEventBase<"run.status", {
  statusLabel: string | null;
}>;

export type StreamRuntimeUpdateEvent = StreamTransportEventBase<"runtime_update", {
  statusLabel: string | null;
}>;

export type StreamContentDeltaEvent = StreamTransportEventBase<"content.delta", {
  delta: string;
  statusLabel: string | null;
}>;

export type StreamContentDoneEvent = StreamTransportEventBase<"content.done", {
  text: string;
}>;

export type StreamToolStartedEvent = StreamTransportEventBase<"tool.started", {
  toolCallId: string;
  toolName: string;
  arguments: KnownToolArgumentsPayload;
  statusLabel: string | null;
  position: number | null;
  sequence: number | null;
}>;

export type StreamToolProgressEvent = StreamTransportEventBase<"tool.progress", {
  toolCallId: string;
  toolName: string;
  query: string | null;
  statusLabel: string | null;
  position: number | null;
  sequence: number | null;
}>;

export type StreamToolCompletedEvent = StreamTransportEventBase<"tool.completed", {
  toolCallId: string;
  toolName: string;
  result: KnownToolResultPayload;
  position: number | null;
  sequence: number | null;
}>;

export type StreamToolFailedEvent = StreamTransportEventBase<"tool.failed", {
  toolCallId: string;
  toolName: string;
  error: ToolErrorPayload;
  position: number | null;
  sequence: number | null;
}>;

export type StreamInputRequestedEvent = StreamTransportEventBase<"input.requested", {
  pendingRequests: StreamPendingRequest[];
  statusLabel: string | null;
}>;

export type StreamErrorEvent = StreamTransportEventBase<"error", {
  message: string;
  code: string | null;
}>;

export type StreamRunFailedEvent = StreamTransportEventBase<"run.failed", {
  message: string;
  code: string | null;
}>;

export type StreamDoneEvent = StreamTransportEventBase<"done", {
  conversationId: string | null;
  runId: string | null;
  runMessageId: string | null;
  assistantMessageId: string | null;
  status: StreamDoneStatus;
  cancelled: boolean;
  pendingRequests: StreamPendingRequest[];
  usage: RunUsagePayload | null;
  conversationUsage: ConversationContextUsage | null;
  elapsedSeconds: number | null;
  costUsd: number | null;
}>;

export type StreamConversationUsageEvent = StreamTransportEventBase<"conversation_usage", {
  source: string | null;
  usage: RunUsagePayload | null;
  conversationUsage: ConversationContextUsage;
}>;

export type StreamTransportEvent =
  | StreamReplayGapEvent
  | StreamNoActiveStreamEvent
  | StreamRunStatusEvent
  | StreamRuntimeUpdateEvent
  | StreamContentDeltaEvent
  | StreamContentDoneEvent
  | StreamToolStartedEvent
  | StreamToolProgressEvent
  | StreamToolCompletedEvent
  | StreamToolFailedEvent
  | StreamInputRequestedEvent
  | StreamErrorEvent
  | StreamRunFailedEvent
  | StreamDoneEvent
  | StreamConversationUsageEvent;

export type StreamEvent = StreamTransportEvent;

function normalizeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function normalizeNonNegativeInt(value: unknown): number | null {
  const normalized = normalizeNumber(value);
  if (normalized == null) return null;
  return Math.max(0, Math.floor(normalized));
}

function normalizeObject(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function parsePendingRequests(raw: unknown): StreamPendingRequest[] {
  if (!Array.isArray(raw)) return [];

  const pendingRequests: StreamPendingRequest[] = [];
  for (const [index, entry] of raw.entries()) {
    try {
      pendingRequests.push(
        parseInteractivePendingRequestTransport(entry, `streamPendingRequests[${index}]`),
      );
    } catch {
      continue;
    }
  }

  return pendingRequests;
}

function parseDoneStatus(rawStatus: unknown, cancelled: boolean): StreamDoneStatus {
  const normalizedStatus = normalizeNonEmptyString(rawStatus)?.toLowerCase();
  if (
    normalizedStatus === "completed" ||
    normalizedStatus === "paused" ||
    normalizedStatus === "cancelled" ||
    normalizedStatus === "failed"
  ) {
    return normalizedStatus;
  }
  return cancelled ? "cancelled" : "completed";
}

function parsePayloadRecord(raw: unknown): JsonRecord | null {
  return isRecord(raw) ? raw : null;
}

function preserveString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseToolOrdering(record: JsonRecord | null): {
  position: number | null;
  sequence: number | null;
} {
  return {
    position: normalizeNonNegativeInt(record?.position ?? record?.pos),
    sequence: normalizeNonNegativeInt(record?.sequence ?? record?.seq),
  };
}

function parseStatusLabel(record: JsonRecord | null): string | null {
  return normalizeNonEmptyString(record?.statusLabel);
}

function parseToolIdentifiers(record: JsonRecord | null): {
  toolCallId: string;
  toolName: ChatToolName;
} | null {
  const toolCallId = normalizeNonEmptyString(record?.toolCallId);
  const toolName = record?.toolName;
  if (!toolCallId || !isChatToolName(toolName)) {
    return null;
  }
  return {
    toolCallId,
    toolName,
  };
}

export function parseStreamEvent(raw: unknown): StreamTransportEvent | null {
  if (!isRecord(raw)) return null;

  const id = normalizeNonNegativeInt(raw.id);
  if (id == null || !isChatStreamEventType(raw.type)) return null;
  const type = raw.type;

  const payload = raw.data;

  switch (type) {
    case "replay_gap": {
      const record = parsePayloadRecord(payload);
      const expectedNextStreamEventId = normalizeNonNegativeInt(record?.expectedNextStreamEventId);
      const resumedAtStreamEventId = normalizeNonNegativeInt(record?.resumedAtStreamEventId);
      if (expectedNextStreamEventId == null) {
        return null;
      }
      return {
        id,
        type,
        data: {
          expectedNextStreamEventId,
          resumedAtStreamEventId:
            resumedAtStreamEventId ?? Math.max(0, expectedNextStreamEventId - 1),
        },
      };
    }

    case "no_active_stream": {
      const record = parsePayloadRecord(payload);
      return {
        id,
        type,
        data: {
          reason: normalizeNonEmptyString(record?.reason),
          conversationId: normalizeNonEmptyString(record?.conversationId),
          runMessageId: normalizeNonEmptyString(record?.runMessageId),
        },
      };
    }

    case "run.status":
    case "runtime_update": {
      const record = parsePayloadRecord(payload);
      return {
        id,
        type,
        data: {
          statusLabel: parseStatusLabel(record),
        },
      };
    }

    case "content.delta": {
      const record = parsePayloadRecord(payload);
      const delta = preserveString(record?.delta) ?? "";
      return {
        id,
        type,
        data: {
          delta,
          statusLabel: parseStatusLabel(record),
        },
      };
    }

    case "content.done": {
      const record = parsePayloadRecord(payload);
      return {
        id,
        type,
        data: {
          text: preserveString(record?.text) ?? "",
        },
      };
    }

    case "tool.started": {
      const record = parsePayloadRecord(payload);
      const ids = parseToolIdentifiers(record);
      if (!ids) return null;
      const ordering = parseToolOrdering(record);
      const rawArguments = normalizeObject(record?.arguments) ?? {};
      let argumentsPayload: KnownToolArgumentsPayload;
      try {
        argumentsPayload = parseToolArgumentsPayloadForTool(
          ids.toolName,
          rawArguments,
          "streamToolStarted.arguments",
        );
      } catch {
        argumentsPayload = rawArguments;
      }
      return {
        id,
        type,
        data: {
          ...ids,
          arguments: argumentsPayload,
          statusLabel: parseStatusLabel(record),
          ...ordering,
        },
      };
    }

    case "tool.progress": {
      const record = parsePayloadRecord(payload);
      const ids = parseToolIdentifiers(record);
      if (!ids) return null;
      const ordering = parseToolOrdering(record);
      return {
        id,
        type,
        data: {
          ...ids,
          query: normalizeNonEmptyString(record?.query),
          statusLabel: parseStatusLabel(record),
          ...ordering,
        },
      };
    }

    case "tool.completed": {
      const record = parsePayloadRecord(payload);
      const ids = parseToolIdentifiers(record);
      if (!ids) return null;
      const ordering = parseToolOrdering(record);
      const rawResult = normalizeObject(record?.result) ?? {};
      try {
        return {
          id,
          type,
          data: {
            ...ids,
            result: parseToolResultPayloadForTool(
              ids.toolName,
              rawResult,
              "streamToolCompleted.result",
            ),
            ...ordering,
          },
        };
      } catch {
        return null;
      }
    }

    case "tool.failed": {
      const record = parsePayloadRecord(payload);
      const ids = parseToolIdentifiers(record);
      if (!ids) return null;
      const ordering = parseToolOrdering(record);
      const rawError = normalizeObject(record?.error) ?? {};
      try {
        return {
          id,
          type,
          data: {
            ...ids,
            error: parseToolErrorPayload(rawError, "streamToolFailed.error"),
            ...ordering,
          },
        };
      } catch {
        return null;
      }
    }

    case "input.requested": {
      const record = parsePayloadRecord(payload);
      return {
        id,
        type,
        data: {
          pendingRequests: parsePendingRequests(record?.pendingRequests),
          statusLabel: parseStatusLabel(record),
        },
      };
    }

    case "error": {
      const record = parsePayloadRecord(payload);
      const message = normalizeNonEmptyString(record?.message) ?? "Generation failed";
      return {
        id,
        type,
        data: {
          message,
          code: normalizeNonEmptyString(record?.code),
        },
      };
    }

    case "run.failed": {
      const record = parsePayloadRecord(payload);
      const message = normalizeNonEmptyString(record?.message) ?? "Generation failed";
      return {
        id,
        type,
        data: {
          message,
          code: normalizeNonEmptyString(record?.code),
        },
      };
    }

    case "done": {
      const record = parsePayloadRecord(payload);
      const cancelled = record?.cancelled === true;
      let usage: RunUsagePayload | null = null;
      const rawUsage = normalizeObject(record?.usage);
      if (rawUsage) {
        try {
          usage = parseRunUsagePayload(rawUsage, "streamDone.usage");
        } catch {
          usage = null;
        }
      }
      let conversationUsage: ConversationContextUsage | null = null;
      const rawConversationUsage = normalizeObject(record?.conversationUsage);
      if (rawConversationUsage) {
        try {
          conversationUsage = parseConversationContextUsage(
            rawConversationUsage,
            "streamDone.conversationUsage",
          );
        } catch {
          conversationUsage = null;
        }
      }
      return {
        id,
        type,
        data: {
          conversationId: normalizeNonEmptyString(record?.conversationId),
          runId: normalizeNonEmptyString(record?.runId),
          runMessageId: normalizeNonEmptyString(record?.runMessageId),
          assistantMessageId: normalizeNonEmptyString(record?.assistantMessageId),
          status: parseDoneStatus(record?.status, cancelled),
          cancelled,
          pendingRequests: parsePendingRequests(record?.pendingRequests),
          usage,
          conversationUsage,
          elapsedSeconds: normalizeNumber(record?.elapsedSeconds),
          costUsd: normalizeNumber(record?.costUsd),
        },
      };
    }

    case "conversation_usage": {
      const record = parsePayloadRecord(payload);
      const rawConversationUsage = normalizeObject(record?.conversationUsage);
      if (!rawConversationUsage) return null;
      let conversationUsage: ConversationContextUsage;
      try {
        conversationUsage = parseConversationContextUsage(
          rawConversationUsage,
          "streamConversationUsage.conversationUsage",
        );
      } catch {
        return null;
      }
      let usage: RunUsagePayload | null = null;
      const rawUsage = normalizeObject(record?.usage);
      if (rawUsage) {
        try {
          usage = parseRunUsagePayload(rawUsage, "streamConversationUsage.usage");
        } catch {
          usage = null;
        }
      }
      return {
        id,
        type,
        data: {
          source: normalizeNonEmptyString(record?.source),
          usage,
          conversationUsage,
        },
      };
    }

    default:
      return null;
  }
}
