import {
  createInitialStreamRuntimeState,
  streamRuntimeReducer,
  type StreamRuntimeAction,
  type StreamRuntimeState,
} from "@/lib/chat/runtime/reducer";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import type { InputGateSlice, Message, QueuedTurn, RunActivityItem, TranscriptSlice } from "@/lib/chat/runtime/types";
import type { TimelineMessagePayload } from "@/lib/contracts/chat";

export type ConversationLifecycleSummary = {
  active: boolean;
  completed: boolean;
  runId: string | null;
  runMessageId: string | null;
  currentStep: string | null;
};

export type ConversationRuntimeRecord = {
  conversationId: string;
  lifecycle: ConversationLifecycleSummary;
  transcript: TranscriptSlice;
  stream: StreamRuntimeState;
  inputGate: InputGateSlice;
  queuedTurns: QueuedTurn[];
  lastEventId: number;
  updatedAtMs: number;
};

export type ConversationLifecycleSeed = {
  conversationId: string;
  runId?: string | null;
  runMessageId?: string | null;
  currentStep?: string | null;
};

export type ChatRuntimeStoreSnapshot = {
  conversations: ReadonlyMap<string, ConversationRuntimeRecord>;
};

export type ChatRuntimeStore = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => ChatRuntimeStoreSnapshot;
  getConversation: (conversationId: string) => ConversationRuntimeRecord;
  replaceActiveStreams: (streams: ConversationLifecycleSeed[]) => void;
  markStarted: (
    conversationId: string,
    runMessageId?: string | null,
    runId?: string | null,
    currentStep?: string | null,
  ) => void;
  markPaused: (conversationId: string) => void;
  markCompleted: (conversationId: string) => void;
  clearCompleted: (conversationId: string) => void;
  setLifecycleCurrentStep: (conversationId: string, currentStep: string | null) => void;
  replaceTranscript: (conversationId: string, transcript: {
    messages: Message[];
    hasMore: boolean;
    nextCursor: string | null;
  }) => void;
  prependTranscript: (conversationId: string, transcript: {
    messages: Message[];
    hasMore: boolean;
    nextCursor: string | null;
  }) => void;
  updateTranscriptMessages: (
    conversationId: string,
    updater: Message[] | ((prev: Message[]) => Message[]),
  ) => void;
  setTranscriptLoading: (
    conversationId: string,
    loading: Partial<Pick<TranscriptSlice, "isLoadingInitial" | "isLoadingMore">>,
  ) => void;
  setTranscriptError: (conversationId: string, error: Error | null) => void;
  applyStreamAction: (conversationId: string, action: StreamRuntimeAction) => void;
  hydrateRuntime: (conversationId: string, runtime: {
    phase: StreamRuntimeState["phase"];
    statusLabel?: string | null;
    draftText?: string | null;
    activityItems?: RunActivityItem[];
    liveMessage?: Message | null;
    runId?: string | null;
    runMessageId?: string | null;
    assistantMessageId?: string | null;
  }) => void;
  setInputGate: (conversationId: string, inputGate: InputGateSlice) => void;
  setQueuedTurns: (conversationId: string, queuedTurns: QueuedTurn[]) => void;
  noteQueuedTurn: (conversationId: string, queuedTurn: QueuedTurn) => void;
  removeQueuedTurn: (conversationId: string, runId: string) => void;
  noteTransportProgress: (
    conversationId: string,
    options?: {
      eventId?: number | null;
      atMs?: number;
      reset?: boolean;
    },
  ) => void;
  resetRuntime: (conversationId: string) => void;
  clearRuntime: (conversationId: string, options?: { preserveCompleted?: boolean }) => void;
  resetAll: () => void;
};

type MutableState = {
  conversations: Map<string, ConversationRuntimeRecord>;
};

function createDefaultConversationRecord(conversationId: string): ConversationRuntimeRecord {
  return {
    conversationId,
    lifecycle: {
      active: false,
      completed: false,
      runId: null,
      runMessageId: null,
      currentStep: null,
    },
    transcript: {
      messages: [],
      hasMore: false,
      nextCursor: null,
      isLoadingInitial: false,
      isLoadingMore: false,
      error: null,
      initialized: false,
      lastSyncedAtMs: 0,
    },
    stream: createInitialStreamRuntimeState(),
    inputGate: {
      isPausedForInput: false,
      pausedPayload: null,
    },
    queuedTurns: [],
    lastEventId: 0,
    updatedAtMs: Date.now(),
  };
}

function areSameQueuedTurns(left: QueuedTurn[], right: QueuedTurn[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((item, index) => {
    const other = right[index];
    return Boolean(
      other &&
      item.queuePosition === other.queuePosition &&
      item.runId === other.runId &&
      item.userMessageId === other.userMessageId &&
      item.blockedByRunId === other.blockedByRunId &&
      item.createdAt === other.createdAt &&
      item.text === other.text
    );
  });
}

function mergeQueuedTurnText(current: QueuedTurn[], incoming: QueuedTurn[]): QueuedTurn[] {
  if (current.length === 0 || incoming.length === 0) {
    return incoming;
  }
  const currentByRunId = new Map(current.map((item) => [item.runId, item]));
  return incoming.map((item) => {
    if (item.text && item.text.trim().length > 0) {
      return item;
    }
    const existing = currentByRunId.get(item.runId);
    if (!existing?.text || existing.text.trim().length === 0) {
      return item;
    }
    return {
      ...item,
      text: existing.text,
    };
  });
}

function dedupeMessages(messages: Message[]): Message[] {
  const seen = new Set<string>();
  const deduped: Message[] = [];
  for (const message of messages) {
    if (seen.has(message.id)) continue;
    seen.add(message.id);
    deduped.push(message);
  }
  return deduped;
}

function resolveMessagePayload(message: Message): TimelineMessagePayload | null {
  return message.metadata?.payload ?? null;
}

function resolveMessageRequestId(message: Message): string | null {
  const payload = resolveMessagePayload(message);
  return normalizeNonEmptyString(payload?.request_id);
}

function isPendingOptimisticUserMessage(message: Message): boolean {
  return (
    message.role === "user" &&
    normalizeNonEmptyString(message.status)?.toLowerCase() === "pending" &&
    resolveMessageRequestId(message) !== null
  );
}

function mergeLatestTranscriptMessages(currentMessages: Message[], nextMessages: Message[]): Message[] {
  if (currentMessages.length === 0) {
    return dedupeMessages(nextMessages);
  }

  const nextIds = new Set<string>();
  const nextRequestIds = new Set<string>();

  for (const message of nextMessages) {
    nextIds.add(message.id);
    const requestId = resolveMessageRequestId(message);
    if (requestId) {
      nextRequestIds.add(requestId);
    }
  }

  const preservedLocalMessages = currentMessages.filter((message) => {
    if (!isPendingOptimisticUserMessage(message)) return false;
    if (nextIds.has(message.id)) return false;

    const requestId = resolveMessageRequestId(message);
    if (!requestId) return false;
    return !nextRequestIds.has(requestId);
  });

  return dedupeMessages([...nextMessages, ...preservedLocalMessages]);
}

export function createChatRuntimeStore(): ChatRuntimeStore {
  let state: MutableState = {
    conversations: new Map<string, ConversationRuntimeRecord>(),
  };
  let snapshot: ChatRuntimeStoreSnapshot = {
    conversations: state.conversations,
  };
  const listeners = new Set<() => void>();

  const emit = () => {
    for (const listener of listeners) {
      listener();
    }
  };

  const withConversation = (
    conversationId: string,
    updater: (current: ConversationRuntimeRecord) => ConversationRuntimeRecord,
  ) => {
    const current = state.conversations.get(conversationId) ?? createDefaultConversationRecord(conversationId);
    const next = updater(current);
    if (next === current) return;
    const nextConversations = new Map(state.conversations);
    nextConversations.set(conversationId, next);
    state = { conversations: nextConversations };
    snapshot = { conversations: nextConversations };
    emit();
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot() {
      return snapshot;
    },
    getConversation(conversationId) {
      return state.conversations.get(conversationId) ?? createDefaultConversationRecord(conversationId);
    },
    replaceActiveStreams(streams) {
      const nextConversations = new Map(state.conversations);
      const activeIds = new Set<string>();

      for (const seed of streams) {
        const conversationId = normalizeNonEmptyString(seed.conversationId);
        if (!conversationId) continue;
        activeIds.add(conversationId);
        const current = nextConversations.get(conversationId) ?? createDefaultConversationRecord(conversationId);
        nextConversations.set(conversationId, {
          ...current,
          lifecycle: {
            active: true,
            completed: false,
            runId: normalizeNonEmptyString(seed.runId),
            runMessageId: normalizeNonEmptyString(seed.runMessageId),
            currentStep: normalizeNonEmptyString(seed.currentStep),
          },
          updatedAtMs: Date.now(),
        });
      }

      for (const [conversationId, current] of nextConversations.entries()) {
        if (!current.lifecycle.active || activeIds.has(conversationId)) continue;
        nextConversations.set(conversationId, {
          ...current,
          lifecycle: {
            active: false,
            completed: current.lifecycle.completed,
            runId: null,
            runMessageId: null,
            currentStep: null,
          },
          updatedAtMs: Date.now(),
        });
      }

      state = { conversations: nextConversations };
      snapshot = { conversations: nextConversations };
      emit();
    },
    markStarted(conversationId, runMessageId, runId, currentStep) {
      withConversation(conversationId, (current) => ({
        ...current,
        lifecycle: {
          active: true,
          completed: false,
          runId: normalizeNonEmptyString(runId),
          runMessageId: normalizeNonEmptyString(runMessageId),
          currentStep: normalizeNonEmptyString(currentStep),
        },
        updatedAtMs: Date.now(),
      }));
    },
    markPaused(conversationId) {
      withConversation(conversationId, (current) => ({
        ...current,
        lifecycle: {
          active: false,
          completed: false,
          runId: null,
          runMessageId: null,
          currentStep: null,
        },
        updatedAtMs: Date.now(),
      }));
    },
    markCompleted(conversationId) {
      withConversation(conversationId, (current) => ({
        ...current,
        lifecycle: {
          active: false,
          completed: true,
          runId: null,
          runMessageId: null,
          currentStep: null,
        },
        updatedAtMs: Date.now(),
      }));
    },
    clearCompleted(conversationId) {
      withConversation(conversationId, (current) => {
        if (!current.lifecycle.completed) return current;
        return {
          ...current,
          lifecycle: {
            ...current.lifecycle,
            completed: false,
          },
          updatedAtMs: Date.now(),
        };
      });
    },
    setLifecycleCurrentStep(conversationId, currentStep) {
      withConversation(conversationId, (current) => ({
        ...current,
        lifecycle: {
          ...current.lifecycle,
          currentStep: normalizeNonEmptyString(currentStep),
        },
        updatedAtMs: Date.now(),
      }));
    },
    replaceTranscript(conversationId, transcript) {
      withConversation(conversationId, (current) => ({
        ...current,
        transcript: {
          ...current.transcript,
          messages: mergeLatestTranscriptMessages(current.transcript.messages, transcript.messages),
          hasMore: transcript.hasMore,
          nextCursor: transcript.nextCursor,
          isLoadingInitial: false,
          isLoadingMore: false,
          error: null,
          initialized: true,
          lastSyncedAtMs: Date.now(),
        },
        updatedAtMs: Date.now(),
      }));
    },
    prependTranscript(conversationId, transcript) {
      withConversation(conversationId, (current) => ({
        ...current,
        transcript: {
          ...current.transcript,
          messages: dedupeMessages([...transcript.messages, ...current.transcript.messages]),
          hasMore: transcript.hasMore,
          nextCursor: transcript.nextCursor,
          isLoadingInitial: false,
          isLoadingMore: false,
          error: null,
          initialized: true,
          lastSyncedAtMs: current.transcript.lastSyncedAtMs,
        },
        updatedAtMs: Date.now(),
      }));
    },
    updateTranscriptMessages(conversationId, updater) {
      withConversation(conversationId, (current) => {
        const nextMessages = typeof updater === "function"
          ? updater(current.transcript.messages)
          : updater;
        return {
          ...current,
          transcript: {
            ...current.transcript,
            messages: dedupeMessages(nextMessages),
            error: null,
            initialized: true,
          },
          updatedAtMs: Date.now(),
        };
      });
    },
    setTranscriptLoading(conversationId, loading) {
      withConversation(conversationId, (current) => ({
        ...current,
        transcript: {
          ...current.transcript,
          isLoadingInitial:
            loading.isLoadingInitial !== undefined
              ? loading.isLoadingInitial
              : current.transcript.isLoadingInitial,
          isLoadingMore:
            loading.isLoadingMore !== undefined
              ? loading.isLoadingMore
              : current.transcript.isLoadingMore,
          error: null,
        },
        updatedAtMs: Date.now(),
      }));
    },
    setTranscriptError(conversationId, error) {
      withConversation(conversationId, (current) => ({
        ...current,
        transcript: {
          ...current.transcript,
          isLoadingInitial: error ? false : current.transcript.isLoadingInitial,
          isLoadingMore: error ? false : current.transcript.isLoadingMore,
          error,
          initialized: current.transcript.initialized || current.transcript.messages.length > 0,
        },
        updatedAtMs: Date.now(),
      }));
    },
    applyStreamAction(conversationId, action) {
      withConversation(conversationId, (current) => ({
        ...current,
        stream: streamRuntimeReducer(current.stream, action),
        updatedAtMs: Date.now(),
      }));
    },
    hydrateRuntime(conversationId, runtime) {
      withConversation(conversationId, (current) => ({
        ...current,
        stream: streamRuntimeReducer(current.stream, {
          type: "hydrate_runtime",
          phase: runtime.phase,
          statusLabel: runtime.statusLabel,
          draftText: runtime.draftText,
          activityItems: runtime.activityItems,
          liveMessage: runtime.liveMessage,
          runId: runtime.runId,
          runMessageId: runtime.runMessageId,
          assistantMessageId: runtime.assistantMessageId,
        }),
        updatedAtMs: Date.now(),
      }));
    },
    setInputGate(conversationId, inputGate) {
      withConversation(conversationId, (current) => ({
        ...current,
        inputGate,
        updatedAtMs: Date.now(),
      }));
    },
    setQueuedTurns(conversationId, queuedTurns) {
      withConversation(conversationId, (current) => {
        const mergedQueuedTurns = mergeQueuedTurnText(current.queuedTurns, queuedTurns);
        if (areSameQueuedTurns(current.queuedTurns, mergedQueuedTurns)) {
          return current;
        }
        return {
          ...current,
          queuedTurns: mergedQueuedTurns,
          updatedAtMs: Date.now(),
        };
      });
    },
    noteQueuedTurn(conversationId, queuedTurn) {
      withConversation(conversationId, (current) => {
        const nextQueuedTurns = [...current.queuedTurns.filter((item) => item.runId !== queuedTurn.runId), queuedTurn]
          .sort((left, right) => left.queuePosition - right.queuePosition);
        if (areSameQueuedTurns(current.queuedTurns, nextQueuedTurns)) {
          return current;
        }
        return {
          ...current,
          queuedTurns: nextQueuedTurns,
          updatedAtMs: Date.now(),
        };
      });
    },
    removeQueuedTurn(conversationId, runId) {
      withConversation(conversationId, (current) => {
        const normalizedRunId = normalizeNonEmptyString(runId);
        if (!normalizedRunId) return current;
        const nextQueuedTurns = current.queuedTurns.filter((item) => item.runId !== normalizedRunId);
        if (nextQueuedTurns.length === current.queuedTurns.length) {
          return current;
        }
        return {
          ...current,
          queuedTurns: nextQueuedTurns,
          updatedAtMs: Date.now(),
        };
      });
    },
    noteTransportProgress(conversationId, options) {
      withConversation(conversationId, (current) => {
        const shouldReset = options?.reset === true;
        const nextEventId =
          typeof options?.eventId === "number" && Number.isFinite(options.eventId)
            ? Math.max(0, Math.floor(options.eventId))
            : current.lastEventId;
        const nextAtMs =
          typeof options?.atMs === "number" && Number.isFinite(options.atMs)
            ? options.atMs
            : Date.now();
        return {
          ...current,
          lastEventId: shouldReset ? nextEventId : Math.max(current.lastEventId, nextEventId),
          updatedAtMs: nextAtMs,
        };
      });
    },
    resetRuntime(conversationId) {
      withConversation(conversationId, (current) => ({
        ...current,
        stream: createInitialStreamRuntimeState(),
        inputGate: {
          isPausedForInput: false,
          pausedPayload: null,
        },
        lastEventId: 0,
        updatedAtMs: Date.now(),
      }));
    },
    clearRuntime(conversationId, options) {
      withConversation(conversationId, (current) => ({
        ...current,
        lifecycle: {
          active: false,
          completed: options?.preserveCompleted === true ? current.lifecycle.completed : false,
          runId: null,
          runMessageId: null,
          currentStep: null,
        },
        stream: createInitialStreamRuntimeState(),
        inputGate: {
          isPausedForInput: false,
          pausedPayload: null,
        },
        lastEventId: 0,
        updatedAtMs: Date.now(),
      }));
    },
    resetAll() {
      const conversations = new Map<string, ConversationRuntimeRecord>();
      state = { conversations };
      snapshot = { conversations };
      emit();
    },
  };
}
