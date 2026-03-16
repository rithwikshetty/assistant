import {
  deriveStreamingStatusFromContent,
  resolveStreamingStatusFromCurrentStep,
  STREAMING_STATUS_AWAITING_INPUT,
  STREAMING_STATUS_IDLE,
  STREAMING_STATUS_MODEL,
  STREAMING_STATUS_STARTING,
  type StreamingStatusState,
} from "@/lib/chat/streaming-status";
import {
  findLatestAssistantMessageForRun,
} from "@/lib/chat/runtime/timeline-repo";
import type { Message, StreamRenderSlice } from "@/lib/chat/runtime/types";
import { isStreamPhaseActive } from "./use-chat-runtime.helpers";

export type StreamDisplayMeta = Pick<
  StreamRenderSlice,
  "assistantMessageId" | "phase" | "runId" | "runMessageId"
> & Partial<Pick<StreamRenderSlice, "draftText" | "activityItems" | "content">>;

function isTerminalAssistantStatus(status: unknown): boolean {
  if (typeof status !== "string") return false;
  const normalized = status.trim().toLowerCase();
  return normalized === "completed" || normalized === "cancelled" || normalized === "failed";
}

export function findTerminalAssistantForActiveStream(args: {
  stream: StreamDisplayMeta;
  messages: Message[];
}): Message | null {
  const { stream, messages } = args;
  const latestAssistantForRun = findLatestAssistantMessageForRun(messages, stream.runId) ??
    (!stream.runId && stream.assistantMessageId
      ? messages.find((message) => message.role === "assistant" && message.id === stream.assistantMessageId) ?? null
      : null);

  if (!latestAssistantForRun || !isTerminalAssistantStatus(latestAssistantForRun.status)) {
    return null;
  }

  return latestAssistantForRun;
}

export function resolveStreamPresence(args: {
  stream: StreamDisplayMeta;
  messages: Message[];
  isPausedForInput: boolean;
}): boolean {
  const { stream, messages, isPausedForInput } = args;

  if (!isStreamPhaseActive(stream.phase) && stream.phase !== "error") {
    return false;
  }

  if (stream.phase === "error") {
    const hasLiveContent =
      (stream.draftText?.length ?? 0) > 0 ||
      (stream.activityItems?.length ?? 0) > 0 ||
      (stream.content?.length ?? 0) > 0;
    if (!hasLiveContent) {
      return false;
    }
  }

  if (stream.phase === "paused_for_input") {
    return true;
  }

  const terminalAssistantForRun = findTerminalAssistantForActiveStream({
    stream,
    messages,
  });
  const hasTerminalAssistantForRun = Boolean(terminalAssistantForRun);
  return !hasTerminalAssistantForRun || isPausedForInput;
}

export type StreamDisplayState = {
  isStreaming: boolean;
  status: StreamingStatusState;
};

export function resolveStreamDisplayState(args: {
  stream: StreamRenderSlice;
  messages: Message[];
  isPausedForInput: boolean;
}): StreamDisplayState {
  const { stream, messages, isPausedForInput } = args;
  const isStreaming = resolveStreamPresence({
    stream,
    messages,
    isPausedForInput,
  });

  if (!isStreaming) {
    return {
      isStreaming: false,
      status: STREAMING_STATUS_IDLE,
    };
  }

  const hasRenderableContent = stream.content.length > 0;
  const derivedFromContent = hasRenderableContent ? deriveStreamingStatusFromContent(stream.content) : null;
  const stepMapped = resolveStreamingStatusFromCurrentStep(stream.statusLabel);
  const status = (() => {
    if (stream.phase === "paused_for_input") {
      return {
        ...STREAMING_STATUS_AWAITING_INPUT,
        label: stream.statusLabel ?? STREAMING_STATUS_AWAITING_INPUT.label,
      };
    }

    if (stream.phase === "starting") {
      if (stepMapped && stepMapped.phase !== "starting") return stepMapped;
      if (stepMapped?.phase === "starting" && derivedFromContent) return derivedFromContent;
      if (derivedFromContent) return derivedFromContent;
      return { ...STREAMING_STATUS_STARTING, label: stream.statusLabel ?? STREAMING_STATUS_STARTING.label };
    }

    if (derivedFromContent?.phase === "tool") {
      return derivedFromContent;
    }

    if (stepMapped) {
      if (stepMapped.phase === "starting" && derivedFromContent) {
        return derivedFromContent;
      }
      return stepMapped;
    }

    return derivedFromContent ?? STREAMING_STATUS_MODEL;
  })();

  return {
    isStreaming,
    status,
  };
}
