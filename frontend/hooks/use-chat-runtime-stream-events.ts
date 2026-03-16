import type {
  Dispatch,
  MutableRefObject,
  SetStateAction,
} from "react";
import type { StreamEvent } from "@/lib/api/chat";
import type { StreamRuntimeAction, StreamRuntimeState } from "@/lib/chat/runtime/reducer";
import type {
  InputGateState,
  RecheckAuthoritativeState,
} from "./use-chat-runtime-stream.types";
import type { RunActivityItem } from "@/lib/chat/runtime/types";

function emitConversationUsageUpdate(args: {
  conversationId: string;
  event: StreamEvent;
}): void {
  const { conversationId, event } = args;
  if (event.type !== "conversation_usage" && event.type !== "done") {
    return;
  }

  const usage = event.data.conversationUsage;
  if (!usage) {
    return;
  }

  try {
    window.dispatchEvent(
      new CustomEvent("frontend:conversationUsageUpdated", {
        detail: {
          conversationId,
          usage:
            event.type === "conversation_usage" && event.data.source
              ? { ...usage, source: event.data.source }
              : usage,
        },
      }),
    );
  } catch {
    // Best effort only.
  }
}

function normalizeStreamErrorCode(rawCode: unknown): string | null {
  if (typeof rawCode !== "string") return null;
  const normalized = rawCode.trim().toLowerCase();
  return normalized.length > 0 ? normalized : null;
}

function isRecoverableStreamErrorCode(code: string | null): boolean {
  return code === "stream_timeout" || code === "stream_disconnected" || code === "connection_lost" || code === "ws_relay";
}

function buildToolActivityItem(args: {
  current: RunActivityItem[];
  event: Extract<
    StreamEvent,
    { type: "tool.started" | "tool.progress" | "tool.completed" | "tool.failed" }
  >;
  runId: string | null;
}): RunActivityItem[] {
  const { current, event, runId } = args;
  const toolCallId = event.data.toolCallId;
  const existingIndex = current.findIndex((item) => (
    item.itemKey === toolCallId ||
    item.itemKey === `tool:${toolCallId}` ||
    item.payload.tool_call_id === toolCallId
  ));
  const now = new Date().toISOString();
  const base: RunActivityItem = existingIndex >= 0
    ? current[existingIndex]
    : {
        id: toolCallId,
        runId: runId ?? "",
        itemKey: toolCallId,
        kind: "tool",
        status: "running",
        title: event.data.toolName,
        summary: null,
        sequence: event.data.sequence ?? (current.length + 1),
        payload: {},
        createdAt: now,
        updatedAt: now,
      };

  let status = base.status;
  const payload: Record<string, unknown> = { ...(base.payload ?? {}) };
  payload.tool_call_id = toolCallId;
  payload.tool_name = event.data.toolName;
  if (event.data.position != null) {
    payload.position = event.data.position;
  }
  if (event.data.sequence != null) {
    payload.sequence = event.data.sequence;
  }
  if (event.type === "tool.started") {
    status = "running";
    payload.arguments = event.data.arguments;
  } else if (event.type === "tool.progress") {
    status = "running";
    if (event.data.query) {
      payload.query = event.data.query;
    }
  } else if (event.type === "tool.completed") {
    status = "completed";
    payload.result = event.data.result;
  } else if (event.type === "tool.failed") {
    status = "failed";
    payload.error = event.data.error;
  }

  const nextItem: RunActivityItem = {
    ...base,
    runId: runId ?? base.runId,
    status,
    title: event.data.toolName,
    sequence: event.data.sequence ?? base.sequence,
    summary:
      event.type === "tool.progress" && event.data.query
        ? event.data.query
        : base.summary,
    payload,
    updatedAt: now,
  };

  if (existingIndex < 0) {
    return [...current, nextItem];
  }
  return current.map((item, index) => (index === existingIndex ? nextItem : item));
}

type CreateStreamEventHandlerArgs = {
  conversationId: string;
  allowNoActiveRecheck?: boolean;
  onNoActiveDuringRecheck?: () => void;
  controller: AbortController;
  mountedRef: MutableRefObject<boolean>;
  streamRef: MutableRefObject<StreamRuntimeState>;
  requestAuthoritativeSync: () => void;
  dispatch: Dispatch<StreamRuntimeAction>;
  setInputGate: Dispatch<SetStateAction<InputGateState>>;
  refetchMessagesRef: MutableRefObject<() => Promise<unknown>>;
  markLocalPause: (conversationId: string) => void;
  markLocalComplete: (conversationId: string) => void;
  clearStreamError: () => void;
  reportStreamError: (nextError: Error, statusLabel?: string) => void;
  recoverRuntimeState: (options?: {
    allowAuthoritativeCheck?: boolean;
    refetchOnIdle?: boolean;
    markCompleteOnIdle?: boolean;
  }) => Promise<RecheckAuthoritativeState>;
};

export function createStreamEventHandler(args: CreateStreamEventHandlerArgs) {
  const {
    conversationId,
    allowNoActiveRecheck,
    onNoActiveDuringRecheck,
    controller,
    mountedRef,
    streamRef,
    requestAuthoritativeSync,
    dispatch,
    setInputGate,
    refetchMessagesRef,
    markLocalPause,
    markLocalComplete,
    clearStreamError,
    reportStreamError,
    recoverRuntimeState,
  } = args;

  const shouldRetryFreshStart = (): boolean => {
    const current = streamRef.current;
    if (current.phase !== "starting" && current.phase !== "streaming") {
      return false;
    }
    if (current.draftText.length > 0 || current.activityItems.length > 0) {
      return false;
    }
    return current.statusLabel === "Starting" || current.statusLabel === "Resuming";
  };

  return async (event: StreamEvent): Promise<void> => {
    if (!mountedRef.current || controller.signal.aborted) return;

    if (event.type === "replay_gap") {
      await recoverRuntimeState({
        allowAuthoritativeCheck: true,
        refetchOnIdle: true,
        markCompleteOnIdle: true,
      });
      return;
    }

    if (event.type === "no_active_stream") {
      if (allowNoActiveRecheck === false) {
        onNoActiveDuringRecheck?.();
        return;
      }
      const recoveryState = await recoverRuntimeState({
        allowAuthoritativeCheck: true,
        refetchOnIdle: true,
        markCompleteOnIdle: true,
      });
      if (recoveryState === "running" && shouldRetryFreshStart()) {
        requestAuthoritativeSync();
      }
      return;
    }

    if (event.type === "conversation_usage" || event.type === "done") {
      emitConversationUsageUpdate({ conversationId, event });
    }

    if (event.type === "done") {
      if (event.data.status === "paused") {
        clearStreamError();
        dispatch({
          type: "set_run_context",
          runId: event.data.runId ?? streamRef.current.runId,
          runMessageId: event.data.runMessageId ?? streamRef.current.runMessageId,
          assistantMessageId: event.data.assistantMessageId ?? streamRef.current.assistantMessageId,
        });
        setInputGate({
          isPausedForInput: event.data.pendingRequests.length > 0,
          pausedPayload:
            event.data.pendingRequests.length > 0
              ? {
                  conversationId,
                  runId: event.data.runId ?? streamRef.current.runId,
                  messageId:
                    event.data.assistantMessageId ??
                    event.data.runMessageId ??
                    streamRef.current.assistantMessageId ??
                    streamRef.current.runMessageId ??
                    `pending-${conversationId}`,
                  requests: event.data.pendingRequests,
                }
              : null,
        });
        dispatch({
          type: "set_phase",
          phase: "paused_for_input",
          statusLabel: "Waiting for your input",
        });
        markLocalPause(conversationId);
        requestAuthoritativeSync();
        return;
      }

      setInputGate({ isPausedForInput: false, pausedPayload: null });
      dispatch({
        type: "set_run_context",
        runId: event.data.runId ?? streamRef.current.runId,
        runMessageId: event.data.runMessageId ?? streamRef.current.runMessageId,
        assistantMessageId: event.data.assistantMessageId ?? streamRef.current.assistantMessageId,
      });

      if (event.data.status === "failed") {
        reportStreamError(new Error("Generation failed"));
        markLocalComplete(conversationId);
        await refetchMessagesRef.current();
        return;
      }

      clearStreamError();
      dispatch({
        type: "set_phase",
        phase: "completing",
      });
      markLocalComplete(conversationId);
      await refetchMessagesRef.current();
      dispatch({ type: "reset" });
      return;
    }

    if (event.type === "error") {
      const errorCode = normalizeStreamErrorCode(event.data.code);
      if (isRecoverableStreamErrorCode(errorCode)) {
        if (allowNoActiveRecheck === false) {
          requestAuthoritativeSync();
          return;
        }
        await recoverRuntimeState({
          allowAuthoritativeCheck: true,
          refetchOnIdle: true,
          markCompleteOnIdle: true,
        });
        return;
      }
      reportStreamError(new Error(event.data.message || "Generation failed"));
      setInputGate({ isPausedForInput: false, pausedPayload: null });
      markLocalComplete(conversationId);
      await refetchMessagesRef.current();
      return;
    }

    if (event.type === "run.failed") {
      reportStreamError(new Error(event.data.message || "Generation failed"));
      setInputGate({ isPausedForInput: false, pausedPayload: null });
      markLocalComplete(conversationId);
      await refetchMessagesRef.current();
      return;
    }

    clearStreamError();

    if (event.type === "runtime_update") {
      requestAuthoritativeSync();
      return;
    }

    if (event.type === "content.delta") {
      dispatch({
        type: "append_delta",
        delta: event.data.delta,
        statusLabel: event.data.statusLabel ?? streamRef.current.statusLabel,
      });
      return;
    }

    if (event.type === "content.done") {
      return;
    }

    if (event.type === "run.status") {
      dispatch({ type: "set_status", statusLabel: event.data.statusLabel });
      requestAuthoritativeSync();
      return;
    }

    if (
      event.type === "tool.started" ||
      event.type === "tool.progress" ||
      event.type === "tool.completed" ||
      event.type === "tool.failed"
    ) {
      dispatch({
        type: "set_activity_items",
        activityItems: buildToolActivityItem({
          current: streamRef.current.activityItems,
          event,
          runId: streamRef.current.runId,
        }),
      });
      if ("statusLabel" in event.data && typeof event.data.statusLabel !== "undefined") {
        dispatch({ type: "set_status", statusLabel: event.data.statusLabel ?? streamRef.current.statusLabel });
      }
      return;
    }

    if (event.type === "input.requested") {
      setInputGate({
        isPausedForInput: true,
        pausedPayload: {
          conversationId,
          runId: streamRef.current.runId,
          messageId:
            streamRef.current.assistantMessageId ??
            streamRef.current.runMessageId ??
            `pending-${conversationId}`,
          requests: event.data.pendingRequests,
        },
      });
      dispatch({
        type: "set_phase",
        phase: "paused_for_input",
        statusLabel: event.data.statusLabel ?? "Waiting for your input",
      });
      markLocalPause(conversationId);
      return;
    }
  };
}
