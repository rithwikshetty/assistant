import type { MutableRefObject, SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { cancelRun, fetchConversationRuntime } from "@/lib/api/chat";
import { queryKeys } from "@/lib/query/query-keys";
import { runChatStreamTransport } from "@/lib/chat/runtime/transport";
import { patchConversationRuntimeInCaches } from "@/lib/chat/conversation-list";
import {
  STREAMING_STATUS_AWAITING_INPUT,
  STREAMING_STATUS_STARTING,
} from "@/lib/chat/streaming-status";
import type { StreamRuntimeAction, StreamRuntimeState } from "@/lib/chat/runtime/reducer";
import {
  fetchConversationTimelinePage,
  resolveMessageText,
  type MessagePage,
} from "@/lib/chat/runtime/timeline-repo";
import type {
  ConnectToStreamArgs,
  InputGateState,
  Message,
  RecheckAuthoritativeState,
} from "@/lib/chat/runtime/types";
import { createStreamEventHandler } from "@/hooks/use-chat-runtime-stream-events";
import {
  resolveAuthoritativeSnapshotFromRuntime,
} from "@/hooks/use-chat-runtime-stream-recovery";
import {
  shouldHydratePausedSnapshot,
  shouldHydrateRunningSnapshot,
} from "@/lib/chat/runtime/authoritative-sync";
import {
  applyOptimisticToolResultToActivityItems,
  projectSettledMessageContent,
} from "@/lib/chat/runtime/activity";
import {
  hydratePausedState,
  resolveReconnectSnapshot,
  type HydratePausedStateOptions,
} from "@/hooks/use-chat-runtime-stream-state";
import {
  sendMessageAction,
} from "@/hooks/use-chat-runtime-stream-actions";
import type { ChatUserEvent } from "@/lib/chat/ws-user-events";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import type {
  ChatRuntimeStore,
  ConversationLifecycleSeed,
  ConversationRuntimeRecord,
} from "@/lib/chat/runtime/store";

const MESSAGE_PAGE_SIZE = 100;
const EVENT_DRIVEN_RUNTIME_SYNC_MS = 100;
const TRANSCRIPT_WARM_CACHE_TTL_MS = 30_000;
const TERMINAL_TRANSCRIPT_SYNC_FRESHNESS_MS = 1_000;

type RuntimeLifecycleEvent = Extract<
  ChatUserEvent,
  { type: "initial_state" | "stream_started" | "stream_resumed" | "stream_paused" | "stream_completed" | "stream_failed" }
>;

type ConversationController = {
  conversationId: string;
  observers: number;
  streamRef: MutableRefObject<StreamRuntimeState>;
  inputGateRef: MutableRefObject<InputGateState>;
  mountedRef: MutableRefObject<boolean>;
  streamAbortControllerRef: MutableRefObject<AbortController | null>;
  createRunAbortControllerRef: MutableRefObject<AbortController | null>;
  recoveryInFlightRef: MutableRefObject<Promise<RecheckAuthoritativeState> | null>;
  transcriptLoadInFlightRef: MutableRefObject<Promise<unknown> | null>;
  loadOlderMessagesInFlightRef: MutableRefObject<Promise<unknown> | null>;
  sawNoActiveDuringRecheckRef: MutableRefObject<boolean>;
  recoveryVersion: number;
  eventDrivenSyncTimer: ReturnType<typeof setTimeout> | null;
  consecutiveSyncFailures: number;
};

export type ConversationRuntimeManager = {
  registerConversation: (conversationId: string) => void;
  unregisterConversation: (conversationId: string) => void;
  bootstrapConversation: (conversationId: string) => Promise<void>;
  refreshConversation: (conversationId: string) => Promise<void>;
  loadOlderMessages: (conversationId: string) => Promise<void>;
  sendMessage: (
    conversationId: string,
    content: string,
    options?: {
      attachmentIds?: string[];
      attachments?: Array<{ id: string; name: string; contentType?: string; fileSize?: number }>;
    },
  ) => Promise<void>;
  stopActiveRun: (conversationId: string) => Promise<void>;
  clearCompleted: (conversationId: string) => void;
  markLocalStart: (
    conversationId: string,
    userMessageId?: string | null,
    runId?: string | null,
    currentStep?: string | null,
    options?: {
      bootstrap?: boolean;
    },
  ) => void;
  markLocalPause: (conversationId: string) => void;
  markLocalComplete: (conversationId: string) => void;
  getActiveRunId: (conversationId: string) => string | null;
  handleLifecycleEvent: (event: RuntimeLifecycleEvent) => void;
  handleInteractiveToolSubmitted: (conversationId: string) => Promise<void>;
  applyOptimisticToolResult: (
    conversationId: string,
    messageId: string,
    toolCallId: string,
    result: Record<string, unknown>,
  ) => void;
  dispose: () => void;
};

function createMutableRef<T>(value: T): MutableRefObject<T> {
  return { current: value };
}


export function createConversationRuntimeManager(args: {
  store: ChatRuntimeStore;
  queryClient: QueryClient;
}): ConversationRuntimeManager {
  const { store, queryClient } = args;
  const controllers = new Map<string, ConversationController>();

  const getRecord = (conversationId: string): ConversationRuntimeRecord => {
    return store.getConversation(conversationId);
  };

  const setMessages = (
    conversationId: string,
    updater: Message[] | ((prev: Message[]) => Message[]),
  ): void => {
    store.updateTranscriptMessages(conversationId, updater);
  };

  const fetchMessagesPage = async (
    conversationId: string,
    cursor?: string | null,
  ): Promise<MessagePage> => {
    return fetchConversationTimelinePage({
      conversationId,
      limit: MESSAGE_PAGE_SIZE,
      cursor: cursor ?? null,
    });
  };

  const ensureController = (conversationId: string): ConversationController => {
    const existing = controllers.get(conversationId);
    if (existing) return existing;

    const record = getRecord(conversationId);
    const controller: ConversationController = {
      conversationId,
      observers: 0,
      streamRef: createMutableRef(record.stream),
      inputGateRef: createMutableRef(record.inputGate),
      mountedRef: createMutableRef(true),
      streamAbortControllerRef: createMutableRef<AbortController | null>(null),
      createRunAbortControllerRef: createMutableRef<AbortController | null>(null),
      recoveryInFlightRef: createMutableRef<Promise<RecheckAuthoritativeState> | null>(null),
      transcriptLoadInFlightRef: createMutableRef<Promise<unknown> | null>(null),
      loadOlderMessagesInFlightRef: createMutableRef<Promise<unknown> | null>(null),
      sawNoActiveDuringRecheckRef: createMutableRef(false),
      recoveryVersion: 0,
      eventDrivenSyncTimer: null,
      consecutiveSyncFailures: 0,
    };
    controllers.set(conversationId, controller);
    return controller;
  };

  const syncControllerRefs = (controller: ConversationController): ConversationRuntimeRecord => {
    const record = getRecord(controller.conversationId);
    controller.streamRef.current = record.stream;
    controller.inputGateRef.current = record.inputGate;
    return record;
  };

  const clearEventDrivenSyncTimer = (controller: ConversationController): void => {
    if (!controller.eventDrivenSyncTimer) return;
    clearTimeout(controller.eventDrivenSyncTimer);
    controller.eventDrivenSyncTimer = null;
  };

  const bumpRecoveryVersion = (controller: ConversationController): void => {
    controller.recoveryVersion += 1;
  };

  const shouldRefetchLatestTranscript = (
    record: ConversationRuntimeRecord,
    nowMs: number = Date.now(),
  ): boolean => {
    if (!record.transcript.initialized) {
      return true;
    }
    const lastSyncedAtMs = record.transcript.lastSyncedAtMs;
    if (!Number.isFinite(lastSyncedAtMs) || lastSyncedAtMs <= 0) {
      return true;
    }
    return nowMs - lastSyncedAtMs >= TRANSCRIPT_WARM_CACHE_TTL_MS;
  };

  const hasFreshTranscriptSync = (
    record: ConversationRuntimeRecord,
    freshnessMs: number,
    nowMs: number = Date.now(),
  ): boolean => {
    const lastSyncedAtMs = record.transcript.lastSyncedAtMs;
    return Number.isFinite(lastSyncedAtMs) && lastSyncedAtMs > 0 && (nowMs - lastSyncedAtMs) < freshnessMs;
  };

  const runRefetchMessagesDeduped = (
    controller: ConversationController,
    options?: { showLoading?: boolean },
  ): Promise<unknown> => {
    const inFlight = controller.transcriptLoadInFlightRef.current;
    if (inFlight) return inFlight;

    const current = syncControllerRefs(controller);
    if (options?.showLoading === true) {
      store.setTranscriptLoading(controller.conversationId, {
        isLoadingInitial: current.transcript.messages.length === 0,
      });
      store.setTranscriptError(controller.conversationId, null);
    }

    let request: Promise<unknown>;
    request = fetchMessagesPage(controller.conversationId, null)
      .then((page) => {
        store.replaceTranscript(controller.conversationId, page);
        return page;
      })
      .catch((error) => {
        const nextError = error instanceof Error ? error : new Error("Failed to load messages");
        store.setTranscriptError(controller.conversationId, nextError);
        throw nextError;
      })
      .finally(() => {
        if (controller.transcriptLoadInFlightRef.current === request) {
          controller.transcriptLoadInFlightRef.current = null;
        }
      });
    controller.transcriptLoadInFlightRef.current = request;
    return request;
  };

  const loadOlderTranscriptPage = async (controller: ConversationController): Promise<void> => {
    const current = syncControllerRefs(controller);
    if (
      current.transcript.isLoadingMore ||
      !current.transcript.hasMore ||
      !current.transcript.nextCursor
    ) {
      return;
    }

    const inFlight = controller.loadOlderMessagesInFlightRef.current;
    if (inFlight) {
      await inFlight;
      return;
    }

    store.setTranscriptLoading(controller.conversationId, { isLoadingMore: true });
    store.setTranscriptError(controller.conversationId, null);

    let request: Promise<void>;
    request = fetchMessagesPage(controller.conversationId, current.transcript.nextCursor)
      .then((page) => {
        store.prependTranscript(controller.conversationId, page);
      })
      .catch((error) => {
        const nextError = error instanceof Error ? error : new Error("Failed to load older messages");
        store.setTranscriptError(controller.conversationId, nextError);
        throw nextError;
      })
      .finally(() => {
        if (controller.loadOlderMessagesInFlightRef.current === request) {
          controller.loadOlderMessagesInFlightRef.current = null;
        }
      });
    controller.loadOlderMessagesInFlightRef.current = request;
    await request;
  };

  const dispatchStreamAction = (controller: ConversationController, action: StreamRuntimeAction): void => {
    store.applyStreamAction(controller.conversationId, action);
    const record = syncControllerRefs(controller);

    if (action.type === "set_phase") {
      if (record.lifecycle.active && action.statusLabel !== undefined) {
        store.setLifecycleCurrentStep(controller.conversationId, action.statusLabel ?? null);
      }
      if (action.phase === "paused_for_input" || action.phase === "idle" || action.phase === "error") {
        clearEventDrivenSyncTimer(controller);
      }
    } else if (
      action.type === "append_delta" ||
      action.type === "set_activity_items" ||
      action.type === "set_run_context" ||
      action.type === "hydrate_runtime"
    ) {
      clearEventDrivenSyncTimer(controller);
    }
  };

  const setInputGateState = (
    controller: ConversationController,
    next: SetStateAction<InputGateState>,
  ): void => {
    const current = controller.inputGateRef.current;
    const resolved = typeof next === "function" ? next(current) : next;
    store.setInputGate(controller.conversationId, resolved);
    syncControllerRefs(controller);
  };

  const clearStreamError = (controller: ConversationController): void => {
    dispatchStreamAction(controller, { type: "set_error", error: null });
  };

  const reportStreamError = (
    controller: ConversationController,
    nextError: Error,
    statusLabel: string = "Generation failed",
  ): void => {
    dispatchStreamAction(controller, { type: "set_error", error: nextError });
    dispatchStreamAction(controller, {
      type: "set_phase",
      phase: "error",
      statusLabel,
    });
  };

  const clearLocalRuntimeState = (
    controller: ConversationController,
    options?: { markComplete?: boolean },
  ): void => {
    controller.streamAbortControllerRef.current?.abort();
    controller.createRunAbortControllerRef.current?.abort();
    controller.streamAbortControllerRef.current = null;
    controller.createRunAbortControllerRef.current = null;
    clearStreamError(controller);
    controller.sawNoActiveDuringRecheckRef.current = false;
    clearEventDrivenSyncTimer(controller);
    store.clearRuntime(controller.conversationId, { preserveCompleted: false });
    if (options?.markComplete !== false) {
      store.markCompleted(controller.conversationId);
      patchConversationRuntimeInCaches(queryClient, {
        conversationId: controller.conversationId,
        updatedAt: new Date().toISOString(),
        awaitingUserInput: false,
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all });
    }
    syncControllerRefs(controller);
  };

  const touchTransportProgress = (
    controller: ConversationController,
    progress?: { eventId?: number | null; reset?: boolean },
  ): void => {
    store.noteTransportProgress(controller.conversationId, {
      eventId: progress?.eventId,
      atMs: Date.now(),
      reset: progress?.reset,
    });
    syncControllerRefs(controller);
  };

  const requestAuthoritativeRuntimeSync = (controller: ConversationController): void => {
    const latest = syncControllerRefs(controller);
    if (controller.observers <= 0 || !controller.mountedRef.current) {
      return;
    }
    if (
      latest.stream.phase !== "starting" &&
      latest.stream.phase !== "streaming" &&
      latest.stream.phase !== "completing"
    ) {
      return;
    }
    if (controller.eventDrivenSyncTimer) {
      return;
    }
    controller.eventDrivenSyncTimer = setTimeout(() => {
      controller.eventDrivenSyncTimer = null;
      void syncAuthoritativeRuntime(controller);
    }, EVENT_DRIVEN_RUNTIME_SYNC_MS);
  };

  const resolveReconnectSnapshotForConversation = (
    controller: ConversationController,
    options?: {
      runId?: string | null;
      runMessageId?: string | null;
      resumeSinceStreamEventId?: number;
      statusLabel?: string | null;
      assistantMessageId?: string | null;
      draftText?: string | null;
      activityItems?: ConversationRuntimeRecord["stream"]["activityItems"];
    },
  ) => {
    return resolveReconnectSnapshot({
      conversationId: controller.conversationId,
      runId: controller.streamRef.current.runId,
      runMessageId: controller.streamRef.current.runMessageId,
      draftText: controller.streamRef.current.draftText,
      activityItems: controller.streamRef.current.activityItems,
      currentStatusLabel: controller.streamRef.current.statusLabel,
      options,
    });
  };

  const hydratePausedStateForConversation = async (
    controller: ConversationController,
    options: HydratePausedStateOptions,
  ): Promise<void> => {
    await hydratePausedState({
      conversationId: controller.conversationId,
      options,
      dispatch: (action) => dispatchStreamAction(controller, action),
      setInputGate: (next) => setInputGateState(controller, next),
      markLocalPause: (conversationId) => markLocalPause(conversationId),
    });
  };

  const applyRunningAuthoritativeState = (
    controller: ConversationController,
    options: {
      runId: string | null;
      runMessageId: string | null;
      resumeSinceStreamEventId: number;
      currentStep: string | null;
      assistantMessageId: string | null;
      draftText: string;
      activityItems: ConversationRuntimeRecord["stream"]["activityItems"];
      liveMessage: ConversationRuntimeRecord["stream"]["liveMessage"];
    },
  ) => {
    clearStreamError(controller);
    const snapshot = resolveReconnectSnapshotForConversation(controller, {
      runId: options.runId,
      runMessageId: options.runMessageId,
      resumeSinceStreamEventId: options.resumeSinceStreamEventId,
      statusLabel: options.currentStep,
      assistantMessageId: options.assistantMessageId,
      draftText: options.draftText,
      activityItems: options.activityItems,
    });

    // Preserve the local statusLabel when the authoritative snapshot has no
    // currentStep — avoids overwriting a meaningful label (e.g. "Starting")
    // with null, which makes the streaming message disappear.
    const resolvedStatusLabel =
      snapshot.statusLabel ?? controller.streamRef.current.statusLabel;

    dispatchStreamAction(controller, {
      type: "hydrate_runtime",
      phase: "streaming",
      statusLabel: resolvedStatusLabel,
      draftText: snapshot.draftText,
      activityItems: snapshot.activityItems,
      liveMessage: options.liveMessage,
      runId: snapshot.runId,
      runMessageId: snapshot.runMessageId,
      assistantMessageId: snapshot.assistantMessageId,
    });
    setInputGateState(controller, { isPausedForInput: false, pausedPayload: null });

    store.markStarted(
      controller.conversationId,
      snapshot.runMessageId,
      snapshot.runId,
      resolvedStatusLabel ?? undefined,
    );
    return snapshot;
  };

  const applyPausedAuthoritativeState = async (
    controller: ConversationController,
    options: {
      runId: string | null;
      runMessageId: string | null;
      pendingRequests: NonNullable<InputGateState["pausedPayload"]>["requests"];
      assistantMessageId: string | null;
      currentStep: string | null;
      draftText: string;
      activityItems: ConversationRuntimeRecord["stream"]["activityItems"];
      liveMessage: ConversationRuntimeRecord["stream"]["liveMessage"];
    },
  ): Promise<void> => {
    clearStreamError(controller);
    await hydratePausedStateForConversation(controller, {
      runId: options.runId,
      runMessageId: options.runMessageId,
      pendingRequests: options.pendingRequests,
      assistantMessageId: options.assistantMessageId,
      statusLabel: options.currentStep ?? STREAMING_STATUS_AWAITING_INPUT.label,
      draftText: options.draftText,
      activityItems: options.activityItems,
      liveMessage: options.liveMessage,
    });
  };

  const syncAuthoritativeRuntime = async (controller: ConversationController): Promise<void> => {
    clearEventDrivenSyncTimer(controller);
    const latest = syncControllerRefs(controller);
    if (controller.observers <= 0 || !controller.mountedRef.current) {
      return;
    }
    if (
      latest.stream.phase !== "starting" &&
      latest.stream.phase !== "streaming" &&
      latest.stream.phase !== "completing"
    ) {
      return;
    }

    try {
      const authoritative = await fetchAuthoritativeSnapshot(controller);
      store.setQueuedTurns(controller.conversationId, authoritative.queuedTurns);
      controller.consecutiveSyncFailures = 0;
      const current = syncControllerRefs(controller);

      if (authoritative.status === "running") {
        if (shouldHydrateRunningSnapshot({
          stream: current.stream,
          authoritative,
          localLastEventId: current.lastEventId,
        })) {
          applyRunningAuthoritativeState(controller, {
            runId: authoritative.runId,
            runMessageId: authoritative.runMessageId,
            resumeSinceStreamEventId: authoritative.resumeSinceStreamEventId,
            currentStep: authoritative.currentStep,
            assistantMessageId: authoritative.assistantMessageId,
            draftText: authoritative.draftText,
            activityItems: authoritative.activityItems,
            liveMessage: authoritative.liveMessage,
          });
        }

        if (!controller.streamAbortControllerRef.current) {
          await connectToStream(
            controller,
            buildAuthoritativeReconnectArgs(controller, authoritative),
          );
          return;
        }
      } else if (authoritative.status === "paused") {
        if (shouldHydratePausedSnapshot({
          stream: current.stream,
          inputGate: current.inputGate,
          authoritative,
        })) {
          await applyPausedAuthoritativeState(controller, {
            runId: authoritative.runId,
            runMessageId: authoritative.runMessageId,
            pendingRequests: authoritative.pendingRequests,
            assistantMessageId: authoritative.assistantMessageId,
            currentStep: authoritative.currentStep ?? STREAMING_STATUS_AWAITING_INPUT.label,
            draftText: authoritative.draftText,
            activityItems: authoritative.activityItems,
            liveMessage: authoritative.liveMessage,
          });
        }
      } else if (
        current.lifecycle.active ||
        current.inputGate.isPausedForInput ||
        current.stream.phase === "starting" ||
        current.stream.phase === "streaming" ||
        current.stream.phase === "completing"
      ) {
        if (shouldRetainFreshLocalStart(current)) {
          return;
        }
        clearLocalRuntimeState(controller, { markComplete: true });
        await runRefetchMessagesDeduped(controller);
      }
    } catch (syncError) {
      controller.consecutiveSyncFailures += 1;
      if (controller.consecutiveSyncFailures >= 3) {
        console.warn(
          `[runtime-sync] ${controller.consecutiveSyncFailures} consecutive /runtime fetch failures for conversation ${controller.conversationId}`,
          syncError instanceof Error ? syncError.message : syncError,
        );
      }
    }
  };

  const fetchAuthoritativeSnapshot = async (controller: ConversationController) => {
    const authoritative = await fetchConversationRuntime(controller.conversationId);
    return resolveAuthoritativeSnapshotFromRuntime(authoritative);
  };

  const buildAuthoritativeReconnectArgs = (
    controller: ConversationController,
    authoritative: Awaited<ReturnType<typeof fetchAuthoritativeSnapshot>>,
  ): ConnectToStreamArgs => {
    const resolvedStatusLabel =
      authoritative.currentStep ??
      controller.streamRef.current.statusLabel ??
      (authoritative.draftText.length > 0 || authoritative.activityItems.length > 0
        ? "Working"
        : STREAMING_STATUS_STARTING.label);

    return {
      sinceStreamEventId: authoritative.resumeSinceStreamEventId,
      draftText: authoritative.draftText,
      activityItems: authoritative.activityItems,
      runId: authoritative.runId,
      runMessageId: authoritative.runMessageId,
      assistantMessageId: authoritative.assistantMessageId,
      statusLabel: resolvedStatusLabel,
      allowNoActiveRecheck: false,
    };
  };

  const resolvePhaseRecoveryState = (controller: ConversationController): RecheckAuthoritativeState => {
    const currentPhase = controller.streamRef.current.phase;
    if (currentPhase === "paused_for_input" || controller.inputGateRef.current.isPausedForInput) {
      return "paused";
    }
    if (currentPhase === "starting" || currentPhase === "streaming" || currentPhase === "completing") {
      return "running";
    }
    return "idle";
  };

  const shouldRetainFreshLocalStart = (record: ConversationRuntimeRecord): boolean => {
    if (!record.lifecycle.active || record.inputGate.isPausedForInput) {
      return false;
    }
    if (record.stream.phase !== "starting" && record.stream.phase !== "streaming") {
      return false;
    }
    if (record.stream.draftText.length > 0 || record.stream.activityItems.length > 0) {
      return false;
    }
    if (record.stream.statusLabel !== "Starting" && record.stream.statusLabel !== "Resuming") {
      return false;
    }
    return record.lastEventId <= 1;
  };

  const lifecycleEventRunIdsMatch = (
    current: ConversationRuntimeRecord,
    event: {
      run_id?: string | null;
      user_message_id?: string | null;
    },
  ): boolean => {
    const expectedRunId = normalizeNonEmptyString(current.stream.runId);
    const expectedRunMessageId = normalizeNonEmptyString(current.stream.runMessageId);
    const incomingRunId = normalizeNonEmptyString(event.run_id);
    const incomingRunMessageId = normalizeNonEmptyString(event.user_message_id);

    if (expectedRunId && incomingRunId !== expectedRunId) {
      return false;
    }
    if (expectedRunMessageId && incomingRunMessageId !== expectedRunMessageId) {
      return false;
    }
    if ((expectedRunId && !incomingRunId) || (expectedRunMessageId && !incomingRunMessageId)) {
      return false;
    }
    return true;
  };

  const findMatchingQueuedTurn = (
    current: ConversationRuntimeRecord,
    event: {
      run_id?: string | null;
      user_message_id?: string | null;
    },
  ) => {
    const incomingRunId = normalizeNonEmptyString(event.run_id);
    const incomingRunMessageId = normalizeNonEmptyString(event.user_message_id);

    if (!incomingRunId && !incomingRunMessageId) {
      return null;
    }

    return current.queuedTurns.find((queuedTurn) => {
      if (incomingRunId && queuedTurn.runId === incomingRunId) {
        return true;
      }
      if (incomingRunMessageId && queuedTurn.userMessageId === incomingRunMessageId) {
        return true;
      }
      return false;
    }) ?? null;
  };

  const lifecycleEventMatchesPausedResume = (
    current: ConversationRuntimeRecord,
    event: {
      run_id?: string | null;
      user_message_id?: string | null;
    },
  ): boolean => {
    if (current.stream.phase !== "paused_for_input" && !current.inputGate.isPausedForInput) {
      return true;
    }
    return lifecycleEventRunIdsMatch(current, event);
  };

  const connectToStream = async (
    controller: ConversationController,
    connectArgs: ConnectToStreamArgs,
  ): Promise<void> => {
    if (!controller.conversationId) return;
    const current = syncControllerRefs(controller);
    const requestedRunMessageId = normalizeNonEmptyString(connectArgs.runMessageId);
    const currentRunMessageId = normalizeNonEmptyString(current.stream.runMessageId);
    const shouldResetTransportCursor =
      connectArgs.sinceStreamEventId < current.lastEventId ||
      requestedRunMessageId !== currentRunMessageId;

    controller.streamAbortControllerRef.current?.abort();
    const transportController = new AbortController();
    controller.streamAbortControllerRef.current = transportController;

    dispatchStreamAction(controller, {
      type: "hydrate_runtime",
      phase: "streaming",
      statusLabel: connectArgs.statusLabel ?? controller.streamRef.current.statusLabel,
      draftText: connectArgs.draftText,
      activityItems: connectArgs.activityItems,
      runId: connectArgs.runId,
      runMessageId: connectArgs.runMessageId,
      assistantMessageId: connectArgs.assistantMessageId,
    });
    clearStreamError(controller);
    touchTransportProgress(controller, {
      eventId: connectArgs.sinceStreamEventId,
      reset: shouldResetTransportCursor,
    });

    try {
      await runChatStreamTransport(controller.conversationId, {
        sinceStreamEventId: connectArgs.sinceStreamEventId,
        runMessageId: connectArgs.runMessageId,
        abortSignal: transportController.signal,
        onTransportProgress: (progress) => {
          touchTransportProgress(controller, progress);
        },
        onEvent: createStreamEventHandler({
          conversationId: controller.conversationId,
          allowNoActiveRecheck: connectArgs.allowNoActiveRecheck,
          onNoActiveDuringRecheck: () => {
            controller.sawNoActiveDuringRecheckRef.current = true;
          },
          controller: transportController,
          mountedRef: controller.mountedRef,
          streamRef: controller.streamRef,
          requestAuthoritativeSync: () => requestAuthoritativeRuntimeSync(controller),
          dispatch: (action) => dispatchStreamAction(controller, action),
          setInputGate: (next) => setInputGateState(controller, next),
          refetchMessagesRef: {
            current: () => runRefetchMessagesDeduped(controller),
          },
          markLocalPause: (conversationId) => markLocalPause(conversationId),
          markLocalComplete: (conversationId) => markLocalComplete(conversationId),
          clearStreamError: () => clearStreamError(controller),
          reportStreamError: (nextError, statusLabel) => reportStreamError(controller, nextError, statusLabel),
          recoverRuntimeState: (options) => recoverRuntimeState(controller, options),
        }),
      });
    } catch (err) {
      if (transportController.signal.aborted || !controller.mountedRef.current) return;
      const streamError = err instanceof Error ? err : new Error("Stream connection lost");

      try {
        const state = await recoverRuntimeState(controller, {
          allowAuthoritativeCheck: true,
        });
        if (state === "running" || state === "paused") {
          return;
        }
      } catch {
        // Keep failure path below.
      }

      reportStreamError(controller, streamError, "Connection lost");
      store.markCompleted(controller.conversationId);
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all });
      await runRefetchMessagesDeduped(controller);
    } finally {
      if (controller.streamAbortControllerRef.current === transportController) {
        controller.streamAbortControllerRef.current = null;
      }
    }
  };

  const applyAuthoritativeSnapshot = async (
    controller: ConversationController,
    authoritative: Awaited<ReturnType<typeof fetchAuthoritativeSnapshot>>,
  ): Promise<RecheckAuthoritativeState> => {
    if (authoritative.status === "running") {
      applyRunningAuthoritativeState(controller, {
        runId: authoritative.runId,
        runMessageId: authoritative.runMessageId,
        resumeSinceStreamEventId: authoritative.resumeSinceStreamEventId,
        currentStep: authoritative.currentStep,
        assistantMessageId: authoritative.assistantMessageId,
        draftText: authoritative.draftText,
        activityItems: authoritative.activityItems,
        liveMessage: authoritative.liveMessage,
      });

      controller.sawNoActiveDuringRecheckRef.current = false;
      await connectToStream(
        controller,
        buildAuthoritativeReconnectArgs(controller, authoritative),
      );

      if (controller.sawNoActiveDuringRecheckRef.current) {
        controller.sawNoActiveDuringRecheckRef.current = false;
        requestAuthoritativeRuntimeSync(controller);
        return resolvePhaseRecoveryState(controller);
      }

      return resolvePhaseRecoveryState(controller);
    }

    if (authoritative.status === "paused") {
      await applyPausedAuthoritativeState(controller, {
        runId: authoritative.runId,
        runMessageId: authoritative.runMessageId,
        pendingRequests: authoritative.pendingRequests,
        assistantMessageId: authoritative.assistantMessageId,
        currentStep: authoritative.currentStep ?? STREAMING_STATUS_AWAITING_INPUT.label,
        draftText: authoritative.draftText,
        activityItems: authoritative.activityItems,
        liveMessage: authoritative.liveMessage,
      });
      return "paused";
    }

    return "idle";
  };

  const recoverRuntimeState = async (
    controller: ConversationController,
    options?: {
      allowAuthoritativeCheck?: boolean;
      refetchOnIdle?: boolean;
      markCompleteOnIdle?: boolean;
    },
  ): Promise<RecheckAuthoritativeState> => {
    const inFlight = controller.recoveryInFlightRef.current;
    if (inFlight) {
      return inFlight;
    }

    const recoveryPromise = (async (): Promise<RecheckAuthoritativeState> => {
      const recoveryVersion = controller.recoveryVersion;
      const allowAuthoritativeCheck = options?.allowAuthoritativeCheck !== false;
      const refetchOnIdle = options?.refetchOnIdle === true;
      const markCompleteOnIdle = options?.markCompleteOnIdle === true;
      const isStaleRecovery = (): boolean => recoveryVersion !== controller.recoveryVersion;

      if (allowAuthoritativeCheck) {
        try {
          const authoritative = await fetchAuthoritativeSnapshot(controller);
          store.setQueuedTurns(controller.conversationId, authoritative.queuedTurns);
          if (isStaleRecovery()) {
            return resolvePhaseRecoveryState(controller);
          }
          const authoritativeState = await applyAuthoritativeSnapshot(controller, authoritative);
          if (authoritativeState === "running" || authoritativeState === "paused") {
            return authoritativeState;
          }
          if (shouldRetainFreshLocalStart(syncControllerRefs(controller))) {
            return resolvePhaseRecoveryState(controller);
          }
          if (isStaleRecovery()) {
            return resolvePhaseRecoveryState(controller);
          }

          clearLocalRuntimeState(controller, {
            markComplete: markCompleteOnIdle,
          });
          if (refetchOnIdle) {
            await runRefetchMessagesDeduped(controller);
          }
          return "idle";
        } catch {
          const localState = resolvePhaseRecoveryState(controller);
          if (localState === "running" || localState === "paused") {
            return localState;
          }
        }
      }

      if (isStaleRecovery()) {
        return resolvePhaseRecoveryState(controller);
      }
      clearLocalRuntimeState(controller, {
        markComplete: markCompleteOnIdle,
      });
      if (refetchOnIdle) {
        await runRefetchMessagesDeduped(controller);
      }
      return "idle";
    })();
    controller.recoveryInFlightRef.current = recoveryPromise;
    try {
      return await recoveryPromise;
    } finally {
      if (controller.recoveryInFlightRef.current === recoveryPromise) {
        controller.recoveryInFlightRef.current = null;
      }
    }
  };

  const getActiveRunId = (conversationId: string): string | null => {
    return getRecord(conversationId).lifecycle.runId ?? null;
  };

  const clearCompleted = (conversationId: string): void => {
    store.clearCompleted(conversationId);
  };

  const markLocalStart = (
    conversationId: string,
    userMessageId?: string | null,
    runId?: string | null,
    currentStep?: string | null,
    options?: {
      bootstrap?: boolean;
    },
  ): void => {
    store.markStarted(conversationId, userMessageId ?? null, runId ?? null, currentStep ?? null);
    patchConversationRuntimeInCaches(queryClient, {
      conversationId,
      updatedAt: new Date().toISOString(),
      awaitingUserInput: false,
    });
    if (options?.bootstrap === false) {
      return;
    }
    const controller = controllers.get(conversationId);
    if (controller && controller.observers > 0 && !controller.streamAbortControllerRef.current) {
      void bootstrapConversation(conversationId);
    }
  };

  const markLocalPause = (conversationId: string): void => {
    store.markPaused(conversationId);
    patchConversationRuntimeInCaches(queryClient, {
      conversationId,
      updatedAt: new Date().toISOString(),
      awaitingUserInput: true,
    });
    const controller = controllers.get(conversationId);
    if (controller) {
      clearEventDrivenSyncTimer(controller);
      syncControllerRefs(controller);
    }
  };

  const markLocalComplete = (conversationId: string): void => {
    store.markCompleted(conversationId);
    patchConversationRuntimeInCaches(queryClient, {
      conversationId,
      updatedAt: new Date().toISOString(),
      awaitingUserInput: false,
    });
    const controller = controllers.get(conversationId);
    if (controller) {
      clearEventDrivenSyncTimer(controller);
      syncControllerRefs(controller);
    }
  };

  const bootstrapConversation = async (conversationId: string): Promise<void> => {
    const controller = ensureController(conversationId);
    const record = syncControllerRefs(controller);
    if (
      record.stream.phase === "starting" ||
      record.stream.phase === "streaming" ||
      record.stream.phase === "paused_for_input" ||
      record.stream.phase === "completing" ||
      record.inputGate.isPausedForInput
    ) {
      return;
    }

    try {
      await recoverRuntimeState(controller, {
        allowAuthoritativeCheck: true,
        refetchOnIdle: false,
        markCompleteOnIdle: false,
      });
    } catch {
      // Stream-state recovery is best effort.
    }
  };

  const registerConversation = (conversationId: string): void => {
    const controller = ensureController(conversationId);
    controller.observers += 1;
    const record = syncControllerRefs(controller);
    if (shouldRefetchLatestTranscript(record)) {
      void runRefetchMessagesDeduped(controller, {
        showLoading: !record.transcript.initialized,
      }).catch(() => undefined);
    }
    void bootstrapConversation(conversationId).catch(() => undefined);
  };

  const unregisterConversation = (conversationId: string): void => {
    const controller = controllers.get(conversationId);
    if (!controller) return;
    controller.observers = Math.max(0, controller.observers - 1);
    if (controller.observers === 0) {
      clearEventDrivenSyncTimer(controller);
    }
    // Intentionally keep active stream controllers alive across route changes.
  };

  const sendMessage = async (
    conversationId: string,
    content: string,
    options?: {
      attachmentIds?: string[];
      attachments?: Array<{ id: string; name: string; contentType?: string; fileSize?: number }>;
    },
  ): Promise<void> => {
    const controller = ensureController(conversationId);
    syncControllerRefs(controller);
    await sendMessageAction({
      conversationId,
      content,
      options,
      inputGateRef: controller.inputGateRef,
      streamRef: controller.streamRef,
      streamAbortControllerRef: controller.streamAbortControllerRef,
      createRunAbortControllerRef: controller.createRunAbortControllerRef,
      getActiveRunId,
      setError: (next) => {
        const resolved = typeof next === "function" ? next(controller.streamRef.current.error) : next;
        dispatchStreamAction(controller, { type: "set_error", error: resolved });
      },
      setMessages: (updater) => setMessages(conversationId, updater),
      setInputGate: (next) => setInputGateState(controller, next),
      dispatch: (action) => dispatchStreamAction(controller, action),
      markLocalStart,
      noteQueuedTurn: (nextConversationId, queuedTurn) => {
        store.noteQueuedTurn(nextConversationId, queuedTurn);
      },
      clearActiveRuntime: (clearOptions) => clearLocalRuntimeState(controller, clearOptions),
      connectToStream: (connectArgs) => connectToStream(controller, connectArgs),
      queryClient,
    });
  };

  const refreshConversation = async (conversationId: string): Promise<void> => {
    const controller = ensureController(conversationId);
    syncControllerRefs(controller);
    await runRefetchMessagesDeduped(controller, { showLoading: false });
  };

  const stopActiveRun = async (conversationId: string): Promise<void> => {
    const controller = ensureController(conversationId);
    const current = syncControllerRefs(controller);
    const runId =
      normalizeNonEmptyString(current.stream.runId) ??
      normalizeNonEmptyString(current.lifecycle.runId);
    if (!runId) {
      return;
    }
    await cancelRun(runId);
    store.setQueuedTurns(conversationId, []);
  };

  const loadOlderMessages = async (conversationId: string): Promise<void> => {
    const controller = ensureController(conversationId);
    syncControllerRefs(controller);
    await loadOlderTranscriptPage(controller);
  };

  const handleLifecycleEvent = (event: RuntimeLifecycleEvent): void => {
    if (event.type === "initial_state") {
      const streams: ConversationLifecycleSeed[] = Array.isArray(event.streams)
        ? event.streams.map((stream) => ({
          conversationId: stream.conversation_id,
          runMessageId: stream.user_message_id ?? null,
          runId: stream.run_id ?? null,
          currentStep: stream.current_step ?? null,
        }))
        : [];
      store.replaceActiveStreams(streams);
      for (const stream of streams) {
        const controller = controllers.get(stream.conversationId);
        if (controller && controller.observers > 0) {
          void bootstrapConversation(stream.conversationId).catch(() => undefined);
        }
      }
      return;
    }

    const conversationId = normalizeNonEmptyString(event.conversation_id);
    if (!conversationId) return;

    if (event.type === "stream_started" || event.type === "stream_resumed") {
      const controller = controllers.get(conversationId);
      const current = controller ? syncControllerRefs(controller) : getRecord(conversationId);
      const matchingQueuedTurn = findMatchingQueuedTurn(current, event);
      if (
        current.stream.phase === "starting" &&
        current.stream.statusLabel === "Queued" &&
        !matchingQueuedTurn
      ) {
        return;
      }
      if (!lifecycleEventMatchesPausedResume(current, event)) {
        return;
      }
      const incomingRunId = normalizeNonEmptyString(event.run_id);
      const incomingRunMessageId = normalizeNonEmptyString(event.user_message_id);
      const isRunSwitch =
        incomingRunId !== normalizeNonEmptyString(current.stream.runId) ||
        incomingRunMessageId !== normalizeNonEmptyString(current.stream.runMessageId);
      const shouldAttachQueuedPromotion = Boolean(
        controller &&
        controller.observers > 0 &&
        matchingQueuedTurn &&
        (
          isRunSwitch ||
          (!controller.streamAbortControllerRef.current &&
            current.stream.phase === "starting" &&
            current.stream.statusLabel === "Queued")
        ),
      );
      const shouldAttachInteractiveResume = Boolean(
        controller &&
        controller.observers > 0 &&
        !controller.streamAbortControllerRef.current &&
        (
          current.stream.phase === "paused_for_input" ||
          current.inputGate.isPausedForInput ||
          (current.stream.phase === "starting" && current.stream.statusLabel === "Resuming")
        ),
      );
      markLocalStart(
        conversationId,
        incomingRunMessageId ?? null,
        incomingRunId ?? null,
        event.current_step ?? null,
        shouldAttachQueuedPromotion || shouldAttachInteractiveResume ? { bootstrap: false } : undefined,
      );
      if (incomingRunId) {
        store.removeQueuedTurn(conversationId, incomingRunId);
      }
      if ((shouldAttachQueuedPromotion || shouldAttachInteractiveResume) && controller && current) {
        bumpRecoveryVersion(controller);
        if (shouldAttachInteractiveResume) {
          setInputGateState(controller, { isPausedForInput: false, pausedPayload: null });
        }
        void connectToStream(controller, {
          sinceStreamEventId: 0,
          draftText: current.stream.draftText,
          activityItems: current.stream.activityItems,
          runId: incomingRunId ?? current.stream.runId,
          runMessageId: incomingRunMessageId ?? current.stream.runMessageId,
          assistantMessageId: shouldAttachQueuedPromotion && isRunSwitch
            ? null
            : current.stream.assistantMessageId,
          statusLabel: normalizeNonEmptyString(event.current_step) ?? (
            shouldAttachInteractiveResume ? "Resuming" : "Starting"
          ),
          allowNoActiveRecheck: true,
        }).catch(() => undefined);
      }
      return;
    }

    if (event.type === "stream_paused") {
      markLocalPause(conversationId);
      const controller = ensureController(conversationId);
      if (controller.observers > 0) {
        void recoverRuntimeState(controller, {
          allowAuthoritativeCheck: true,
          refetchOnIdle: false,
          markCompleteOnIdle: false,
        }).catch(() => undefined);
      }
      if (!hasFreshTranscriptSync(syncControllerRefs(controller), TERMINAL_TRANSCRIPT_SYNC_FRESHNESS_MS)) {
        void runRefetchMessagesDeduped(controller, { showLoading: false }).catch(() => undefined);
      }
      return;
    }

    const controller = controllers.get(conversationId);
    if (controller && controller.observers === 0) {
      clearLocalRuntimeState(controller, { markComplete: true });
    } else {
      markLocalComplete(conversationId);
    }
    if (controller) {
      if (!hasFreshTranscriptSync(syncControllerRefs(controller), TERMINAL_TRANSCRIPT_SYNC_FRESHNESS_MS)) {
        void runRefetchMessagesDeduped(controller, { showLoading: false }).catch(() => undefined);
      }
    }
  };

  const handleInteractiveToolSubmitted = async (conversationId: string): Promise<void> => {
    const controller = ensureController(conversationId);
    syncControllerRefs(controller);
    const previousInputGate = controller.inputGateRef.current;
    const runId = previousInputGate.pausedPayload?.runId ?? controller.streamRef.current.runId;
    const runMessageId = controller.streamRef.current.runMessageId;
    const assistantMessageId =
      previousInputGate.pausedPayload?.messageId ?? controller.streamRef.current.assistantMessageId;

    // Interactive submit must force a fresh authoritative read. Reusing an
    // older in-flight paused recovery can pin the UI back to Waiting for input
    // even after the backend has already accepted the answer and resumed.
    bumpRecoveryVersion(controller);
    const recoveryVersion = controller.recoveryVersion;
    const isStaleRecovery = (): boolean => recoveryVersion !== controller.recoveryVersion;
    controller.recoveryInFlightRef.current = null;

    setInputGateState(controller, { isPausedForInput: false, pausedPayload: null });
    dispatchStreamAction(controller, {
      type: "set_phase",
      phase: "starting",
      statusLabel: "Resuming",
      runId,
      runMessageId,
      assistantMessageId,
    });
    markLocalStart(
      conversationId,
      runMessageId,
      runId,
      "Resuming",
      { bootstrap: false },
    );
    try {
      const authoritative = await fetchAuthoritativeSnapshot(controller);
      store.setQueuedTurns(controller.conversationId, authoritative.queuedTurns);
      if (isStaleRecovery()) {
        return;
      }

      if (authoritative.status === "running") {
        await applyAuthoritativeSnapshot(controller, authoritative);
        return;
      }

      if (authoritative.status === "paused") {
        await applyPausedAuthoritativeState(controller, {
          runId: authoritative.runId,
          runMessageId: authoritative.runMessageId,
          pendingRequests: authoritative.pendingRequests,
          assistantMessageId: authoritative.assistantMessageId,
          currentStep: authoritative.currentStep ?? STREAMING_STATUS_AWAITING_INPUT.label,
          draftText: authoritative.draftText,
          activityItems: authoritative.activityItems,
          liveMessage: authoritative.liveMessage,
        });
        return;
      }

      clearLocalRuntimeState(controller, { markComplete: true });
      await runRefetchMessagesDeduped(controller);
    } catch {
      if (previousInputGate.isPausedForInput) {
        dispatchStreamAction(controller, {
          type: "hydrate_runtime",
          phase: "paused_for_input",
          statusLabel: controller.streamRef.current.statusLabel ?? STREAMING_STATUS_AWAITING_INPUT.label,
          draftText: controller.streamRef.current.draftText,
          activityItems: controller.streamRef.current.activityItems,
          liveMessage: controller.streamRef.current.liveMessage,
          runId,
          runMessageId,
          assistantMessageId,
        });
        setInputGateState(controller, previousInputGate);
        markLocalPause(conversationId);
      }
    }
  };

  const applyOptimisticToolResult = (
    conversationId: string,
    messageId: string,
    toolCallId: string,
    result: Record<string, unknown>,
  ): void => {
    const controller = controllers.get(conversationId);
    if (controller) {
      syncControllerRefs(controller);
      const nextActivityItems = applyOptimisticToolResultToActivityItems({
        activityItems: controller.streamRef.current.activityItems,
        toolCallId,
        result,
      });
      if (nextActivityItems) {
        dispatchStreamAction(controller, {
          type: "set_activity_items",
          activityItems: nextActivityItems,
        });
      }
    }

    store.updateTranscriptMessages(conversationId, (messages) =>
      messages.map((message) => {
        if (message.id !== messageId) return message;
        const nextActivityItems = applyOptimisticToolResultToActivityItems({
          activityItems: message.activityItems ?? [],
          toolCallId,
          result,
        });
        if (!nextActivityItems) return message;
        return {
          ...message,
          activityItems: nextActivityItems,
          content: projectSettledMessageContent({
            text: resolveMessageText(message),
            activityItems: nextActivityItems,
          }),
          metadata: {
            ...(message.metadata ?? {}),
            activity_item_count: nextActivityItems.length,
          },
        };
      }),
    );
  };

  const dispose = (): void => {
    for (const controller of controllers.values()) {
      controller.mountedRef.current = false;
      controller.streamAbortControllerRef.current?.abort();
      controller.createRunAbortControllerRef.current?.abort();
      clearEventDrivenSyncTimer(controller);
    }
    controllers.clear();
  };

  return {
    registerConversation,
    unregisterConversation,
    bootstrapConversation,
    refreshConversation,
    loadOlderMessages,
    sendMessage,
    stopActiveRun,
    clearCompleted,
    markLocalStart,
    markLocalPause,
    markLocalComplete,
    getActiveRunId,
    handleLifecycleEvent,
    handleInteractiveToolSubmitted,
    applyOptimisticToolResult,
    dispose,
  };
}
