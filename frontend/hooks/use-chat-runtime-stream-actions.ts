import type {
  Dispatch,
  MutableRefObject,
  SetStateAction,
} from "react";
import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { createRun } from "@/lib/api/chat";
import type { ConversationSummary } from "@/lib/api/auth";
import { patchConversationRuntimeInCaches } from "@/lib/chat/conversation-list";
import { STREAMING_STATUS_STARTING } from "@/lib/chat/streaming-status";
import { queryKeys } from "@/lib/query/query-keys";
import { normalizeNonEmptyString } from "@/lib/chat/runtime/timeline-repo";
import type { StreamRuntimeAction, StreamRuntimeState } from "@/lib/chat/runtime/reducer";
import type { Message } from "@/lib/chat/runtime/types";
import {
  isAbortError,
  isStreamPhaseActive,
} from "./use-chat-runtime.helpers";
import type {
  ConnectToStreamArgs,
  InputGateState,
  QueuedTurn,
  SetMessagesFn,
} from "./use-chat-runtime-stream.types";

export type SendMessageActionOptions = {
  attachmentIds?: string[];
  attachments?: Array<{ id: string; name: string; contentType?: string; fileSize?: number }>;
};

export type SendMessageActionArgs = {
  conversationId: string;
  content: string;
  options?: SendMessageActionOptions;
  inputGateRef: MutableRefObject<InputGateState>;
  streamRef: MutableRefObject<StreamRuntimeState>;
  streamAbortControllerRef: MutableRefObject<AbortController | null>;
  createRunAbortControllerRef: MutableRefObject<AbortController | null>;
  getActiveRunId: (conversationId: string) => string | null;
  setError: Dispatch<SetStateAction<Error | null>>;
  setMessages: SetMessagesFn;
  setInputGate: Dispatch<SetStateAction<InputGateState>>;
  dispatch: Dispatch<StreamRuntimeAction>;
  markLocalStart: (
    conversationId: string,
    userMessageId?: string | null,
    runId?: string | null,
    currentStep?: string | null,
    options?: {
      bootstrap?: boolean;
    },
  ) => void;
  noteQueuedTurn?: (conversationId: string, queuedTurn: QueuedTurn) => void;
  clearActiveRuntime: (options?: { markComplete?: boolean }) => void;
  onError?: (error: Error) => void;
  connectToStream: (args: ConnectToStreamArgs) => Promise<void>;
  queryClient: QueryClient;
};

type ConversationRuntimeRollbackSnapshot = {
  queryKey: QueryKey;
  previous: ConversationSummary;
  optimistic: Pick<
    ConversationSummary,
    "updated_at" | "last_message_at" | "message_count" | "last_message_preview" | "awaiting_user_input"
  >;
};

function matchesOptimisticConversationState(
  conversation: ConversationSummary,
  snapshot: ConversationRuntimeRollbackSnapshot,
): boolean {
  return (
    conversation.updated_at === snapshot.optimistic.updated_at &&
    conversation.last_message_at === snapshot.optimistic.last_message_at &&
    conversation.message_count === snapshot.optimistic.message_count &&
    conversation.last_message_preview === snapshot.optimistic.last_message_preview &&
    conversation.awaiting_user_input === snapshot.optimistic.awaiting_user_input
  );
}

function captureConversationRuntimeRollbackSnapshots(args: {
  queryClient: QueryClient;
  conversationId: string;
  updatedAt: string;
  lastMessageAt: string;
  lastMessagePreview: string;
}): ConversationRuntimeRollbackSnapshot[] {
  const {
    queryClient,
    conversationId,
    updatedAt,
    lastMessageAt,
    lastMessagePreview,
  } = args;

  return queryClient
    .getQueriesData<ConversationSummary[]>({ queryKey: queryKeys.conversations.all })
    .flatMap(([queryKey, conversations]) => {
      const previous = (conversations ?? []).find((conversation) => conversation.id === conversationId);
      if (!previous) {
        return [];
      }
      return [{
        queryKey,
        previous,
        optimistic: {
          updated_at: updatedAt,
          last_message_at: lastMessageAt,
          message_count: Math.max(0, previous.message_count + 1),
          last_message_preview: lastMessagePreview,
          awaiting_user_input: false,
        },
      }];
    });
}

function rollbackConversationRuntimePatch(
  queryClient: QueryClient,
  snapshots: ConversationRuntimeRollbackSnapshot[],
): void {
  for (const snapshot of snapshots) {
    queryClient.setQueryData<ConversationSummary[]>(snapshot.queryKey, (current) => {
      if (!current || current.length === 0) {
        return current;
      }
      const next = current.slice();
      const index = next.findIndex((conversation) => conversation.id === snapshot.previous.id);
      if (index === -1) {
        return current;
      }
      if (!matchesOptimisticConversationState(next[index]!, snapshot)) {
        return current;
      }
      next[index] = snapshot.previous;
      return next;
    });
  }
}

export async function sendMessageAction(args: SendMessageActionArgs): Promise<void> {
  const {
    conversationId,
    content,
    options,
    inputGateRef: _inputGateRef,
    streamRef,
    streamAbortControllerRef,
    createRunAbortControllerRef,
    getActiveRunId: _getActiveRunId,
    setError,
    setMessages,
    setInputGate,
    dispatch,
    markLocalStart,
    noteQueuedTurn,
    clearActiveRuntime,
    onError,
    connectToStream,
    queryClient,
  } = args;

  if (!conversationId) return;

  const requestId = (() => {
    try {
      return crypto?.randomUUID?.() ?? `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    } catch {
      return `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    }
  })();
  const nowIso = new Date().toISOString();
  const rollbackSnapshots = captureConversationRuntimeRollbackSnapshots({
    queryClient,
    conversationId,
    updatedAt: nowIso,
    lastMessageAt: nowIso,
    lastMessagePreview: content,
  });

  setError(null);

  const hadActiveStream =
    streamRef.current.phase !== "completing" &&
    isStreamPhaseActive(streamRef.current.phase);

  const optimisticUserMessage: Message = {
    id: `temp_${Date.now()}_${Math.random()}`,
    role: "user",
    content: [{ type: "text", text: content }],
    createdAt: new Date(),
    attachments: options?.attachments,
    metadata: {
      event_type: "user_message",
      payload: {
        text: content,
        request_id: requestId,
      },
      run_id: null,
      activity_item_count: 0,
      stream_checkpoint_event_id: null,
    },
    status: "pending",
  };
  const shouldInsertOptimisticTranscript = !hadActiveStream;

  if (shouldInsertOptimisticTranscript) {
    setMessages((prev) => [...prev, optimisticUserMessage]);
  }
  setInputGate({ isPausedForInput: false, pausedPayload: null });
  patchConversationRuntimeInCaches(queryClient, {
    conversationId,
    updatedAt: nowIso,
    lastMessageAt: nowIso,
    lastMessagePreview: content,
    messageCountDelta: 1,
    awaitingUserInput: false,
  });

  if (streamRef.current.phase === "completing") {
    streamAbortControllerRef.current?.abort();
    streamAbortControllerRef.current = null;
  }

  if (!hadActiveStream) {
    dispatch({ type: "reset" });
    dispatch({
      type: "set_phase",
      phase: "starting",
      statusLabel: STREAMING_STATUS_STARTING.label,
      runId: null,
      runMessageId: null,
      assistantMessageId: null,
    });
  }

  const createController = new AbortController();
  createRunAbortControllerRef.current = createController;

  try {
    const runResult = await createRun({
      conversationId,
      text: content,
      requestId,
      attachmentIds: options?.attachmentIds,
      abortSignal: createController.signal,
    });

    const runId = normalizeNonEmptyString(runResult.run_id);
    const runMessageId = normalizeNonEmptyString(runResult.user_message_id);
    const persistedUserMessageId = normalizeNonEmptyString(runResult.user_message_id) ?? optimisticUserMessage.id;

    if (shouldInsertOptimisticTranscript) {
      setMessages((prev) => prev.map((msg) => {
        if (msg.id !== optimisticUserMessage.id) return msg;
        return {
          ...msg,
          id: persistedUserMessageId,
          status: "pending",
        };
      }));
    }

    if (!hadActiveStream && runResult.status !== "queued") {
      dispatch({
        type: "set_phase",
        phase: "streaming",
        statusLabel: STREAMING_STATUS_STARTING.label,
        runId,
        runMessageId,
      });

      markLocalStart(
        conversationId,
        runMessageId,
        runId,
        STREAMING_STATUS_STARTING.label ?? undefined,
        { bootstrap: false },
      );

      await connectToStream({
        sinceStreamEventId: 0,
        draftText: "",
        activityItems: [],
        runId,
        runMessageId,
        assistantMessageId: null,
        statusLabel: STREAMING_STATUS_STARTING.label,
      });
    } else if (!hadActiveStream && runResult.status === "queued") {
      dispatch({
        type: "set_phase",
        phase: "starting",
        statusLabel: "Queued",
        runId,
        runMessageId,
        assistantMessageId: null,
      });
    }

    if (runResult.status === "queued" && runId && runMessageId) {
      noteQueuedTurn?.(conversationId, {
        queuePosition: Math.max(1, runResult.queue_position || 1),
        runId,
        userMessageId: runMessageId,
        blockedByRunId: streamRef.current.runId ?? null,
        createdAt: nowIso,
        text: content,
      });
    }
  } catch (err) {
    if (!isAbortError(err)) {
      const sendError = err instanceof Error ? err : new Error("Failed to send message");
      setError(sendError);
      onError?.(sendError);
    }

    if (!hadActiveStream) {
      clearActiveRuntime({ markComplete: false });
    }
    rollbackConversationRuntimePatch(queryClient, rollbackSnapshots);
    if (shouldInsertOptimisticTranscript) {
      setMessages((prev) => prev.filter((msg) => msg.id !== optimisticUserMessage.id));
    }
  } finally {
    if (createRunAbortControllerRef.current === createController) {
      createRunAbortControllerRef.current = null;
    }
  }
}
