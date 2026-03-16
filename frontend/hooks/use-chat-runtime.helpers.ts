import type {
  Message,
  StreamDisplaySlice,
  StreamRenderSlice,
  UserInputPayload,
} from "@/lib/chat/runtime/types";
import type { StreamStatePendingRequestResponse } from "@/lib/contracts/chat";
import { toTransportPendingRequest } from "@/lib/contracts/chat-interactive";
import type { StreamRuntimeState } from "@/lib/chat/runtime/reducer";

export function isAbortError(error: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

export function mapTransportPendingRequests(
  raw: StreamStatePendingRequestResponse[],
): UserInputPayload["requests"] {
  return raw.map((entry) => toTransportPendingRequest(entry));
}

export function isStreamPhaseActive(phase: StreamRuntimeState["phase"]): boolean {
  return phase === "starting" || phase === "streaming" || phase === "paused_for_input" || phase === "completing";
}

function isTransientAssistantMessage(message: Message): boolean {
  return (
    message.role === "assistant" &&
    (message.status === "streaming" || message.status === "awaiting_input")
  );
}

function resolveMessageRunId(message: Message): string | null {
  const runId = message.metadata?.run_id;
  return typeof runId === "string" && runId.trim().length > 0 ? runId.trim() : null;
}

function isSupersededTransientAssistantMessage(
  message: Message,
  stream: StreamRenderSlice,
): boolean {
  if (!isTransientAssistantMessage(message)) {
    return false;
  }

  if (stream.assistantMessageId && message.id === stream.assistantMessageId) {
    return true;
  }

  const messageRunId = resolveMessageRunId(message);
  return Boolean(stream.runId && messageRunId && messageRunId === stream.runId);
}

export function buildTranscriptTimeline(
  messages: Message[],
  stream?: StreamRenderSlice,
): Message[] {
  if (!stream) {
    return messages.filter((message) => !isTransientAssistantMessage(message));
  }
  return messages.filter((message) => !isSupersededTransientAssistantMessage(message, stream));
}

function buildSyntheticStreamMessageId(args: {
  conversationId: string;
  stream: StreamRenderSlice;
}): string {
  return (
    args.stream.assistantMessageId ??
    args.stream.runId ??
    args.stream.runMessageId ??
    `stream:${args.conversationId}`
  );
}

function buildStreamingPlaceholderMessage(args: {
  conversationId: string;
  stream: StreamRenderSlice;
  createdAt: Date;
  status: "streaming" | "awaiting_input";
  streamDisplay: StreamDisplaySlice;
}): Message {
  const payload =
    args.stream.runId || args.stream.draftText.length > 0
      ? {
          run_id: args.stream.runId ?? null,
          text: args.stream.draftText,
          status: args.status,
        }
      : null;

  return {
    id: buildSyntheticStreamMessageId({
      conversationId: args.conversationId,
      stream: args.stream,
    }),
    role: "assistant",
    content: args.stream.content,
    activityItems: args.stream.activityItems,
    createdAt: args.createdAt,
    streamingStatus: args.streamDisplay.status,
    metadata: {
      run_id: args.stream.runId ?? null,
      synthetic_stream: true,
      ...(payload ? { payload } : {}),
    },
    status: args.status,
    responseLatencyMs: null,
    finishReason: null,
    userFeedbackId: null,
    userFeedbackRating: null,
    userFeedbackUpdatedAt: null,
    suggestedQuestions: null,
  };
}

export function buildStreamingTimeline(args: {
  conversationId: string;
  messages: Message[];
  stream: StreamRenderSlice;
  streamDisplay: StreamDisplaySlice;
  isPausedForInput: boolean;
}): Message[] {
  const transcriptTimeline = buildTranscriptTimeline(args.messages, args.stream);
  if (!args.streamDisplay.isStreaming) {
    return transcriptTimeline;
  }

  const lastCreatedAt = transcriptTimeline[transcriptTimeline.length - 1]?.createdAt;
  const createdAt =
    lastCreatedAt instanceof Date && Number.isFinite(lastCreatedAt.getTime())
      ? new Date(lastCreatedAt.getTime() + 1)
      : new Date(0);
  const status =
    args.isPausedForInput || args.stream.phase === "paused_for_input" ? "awaiting_input" : "streaming";
  const liveMessage = args.stream.liveMessage;

  if (liveMessage) {
    return [
      ...transcriptTimeline,
      {
        ...liveMessage,
        streamingStatus: args.streamDisplay.status,
        status,
        metadata: {
          ...(liveMessage.metadata ?? {}),
          run_id: liveMessage.metadata?.run_id ?? args.stream.runId ?? null,
          live_message: true,
        },
      },
    ];
  }

  return [
    ...transcriptTimeline,
    buildStreamingPlaceholderMessage({
      conversationId: args.conversationId,
      stream: args.stream,
      createdAt,
      status,
      streamDisplay: args.streamDisplay,
    }),
  ];
}
