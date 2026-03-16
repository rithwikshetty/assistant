/* @refresh skip */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { usePreferences } from "@/contexts/preferences-context";
import { playNotificationSound } from "@/lib/utils/notification-sound";
import {
  createConversationRuntimeManager,
  type ConversationRuntimeManager,
} from "@/lib/chat/runtime/manager";
import {
  createChatRuntimeStore,
  type ChatRuntimeStore,
  type ConversationRuntimeRecord,
} from "@/lib/chat/runtime/store";
import {
  disposeChatWsTransport,
  getChatWsTransport,
} from "@/lib/chat/wsTransport";
import { patchConversationTitleInCaches } from "@/lib/chat/conversation-list";
import type { InputGateSlice, QueuedTurn, StreamRenderSlice, TranscriptSlice } from "@/lib/chat/runtime/types";

type ActiveStreamsContextValue = {
  store: ChatRuntimeStore;
  manager: ConversationRuntimeManager;
};

const ActiveStreamsContext = createContext<ActiveStreamsContextValue | null>(null);
let activeStreamsRuntimeRef: ActiveStreamsContextValue | null = null;

function createActiveStreamsRuntime(queryClient: ReturnType<typeof useQueryClient>): ActiveStreamsContextValue {
  const store = createChatRuntimeStore();
  const manager = createConversationRuntimeManager({
    store,
    queryClient,
  });
  return {
    store,
    manager,
  };
}

export function ActiveStreamsProvider({ children }: { children: ReactNode }) {
  const { isLoading, isBackendAuthenticated } = useAuth();
  const { preferences } = usePreferences();
  const queryClient = useQueryClient();
  const runtimeRef = useRef<ActiveStreamsContextValue | null>(null);

  if (!runtimeRef.current) {
    runtimeRef.current = createActiveStreamsRuntime(queryClient);
    activeStreamsRuntimeRef = runtimeRef.current;
  }

  const runtime = runtimeRef.current;

  const notificationSoundEnabled = preferences?.notification_sound !== false;
  const notificationSoundRef = useRef(notificationSoundEnabled);
  notificationSoundRef.current = notificationSoundEnabled;

  useEffect(() => {
    return () => {
      disposeChatWsTransport();
      runtime.manager.dispose();
      runtime.store.resetAll();
      if (activeStreamsRuntimeRef === runtime) {
        activeStreamsRuntimeRef = null;
      }
    };
  }, [runtime]);

  useEffect(() => {
    if (isLoading || !isBackendAuthenticated) {
      disposeChatWsTransport();
      runtime.manager.dispose();
      runtime.store.resetAll();
      return;
    }

    const transport = getChatWsTransport();
    const unsubscribe = transport.subscribeUserEvents((event) => {
      if (event.type === "conversation_title_updated") {
        patchConversationTitleInCaches(queryClient, {
          conversationId: event.conversation_id ?? "",
          title: event.title ?? null,
          updatedAt: event.updated_at ?? null,
        });
        try {
          window.dispatchEvent(
            new CustomEvent("backend:titleUpdated", {
              detail: {
                conversationId: event.conversation_id,
                title: event.title ?? null,
                updatedAt: event.updated_at ?? null,
              },
            }),
          );
        } catch {}
        return;
      }

      runtime.manager.handleLifecycleEvent(event);

      if (event.type === "stream_completed" || event.type === "stream_failed") {
        if (notificationSoundRef.current) {
          playNotificationSound();
        }
      }
    });

    return () => {
      unsubscribe();
    };
  }, [isBackendAuthenticated, isLoading, queryClient, runtime]);

  return (
    <ActiveStreamsContext.Provider value={runtime}>
      {children}
    </ActiveStreamsContext.Provider>
  );
}

function useActiveStreamsRuntime(): ActiveStreamsContextValue {
  const context = useContext(ActiveStreamsContext);
  if (!context) {
    throw new Error("useActiveStreams must be used within ActiveStreamsProvider");
  }
  return context;
}

export function useActiveStreams() {
  const runtime = useActiveStreamsRuntime();
  const snapshot = useSyncExternalStore(
    runtime.store.subscribe,
    runtime.store.getSnapshot,
    runtime.store.getSnapshot,
  );

  const activeStreamIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [conversationId, record] of snapshot.conversations.entries()) {
      if (record.lifecycle.active) {
        ids.add(conversationId);
      }
    }
    return ids;
  }, [snapshot]);

  const completedStreamIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [conversationId, record] of snapshot.conversations.entries()) {
      if (record.lifecycle.completed) {
        ids.add(conversationId);
      }
    }
    return ids;
  }, [snapshot]);

  return {
    activeStreamIds,
    completedStreamIds,
    clearCompleted: runtime.manager.clearCompleted,
    markLocalStart: runtime.manager.markLocalStart,
    markLocalPause: runtime.manager.markLocalPause,
    markLocalComplete: runtime.manager.markLocalComplete,
    getActiveRunId: runtime.manager.getActiveRunId,
  };
}

export function useConversationRuntimeManager(): ConversationRuntimeManager {
  return useActiveStreamsRuntime().manager;
}

function shallowEqualObject<T extends Record<string, unknown>>(left: T, right: T): boolean {
  if (Object.is(left, right)) return true;
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => Object.is(left[key], right[key]));
}

function useConversationSelector<T>(
  conversationId: string,
  selector: (record: ConversationRuntimeRecord) => T,
  isEqual: (left: T, right: T) => boolean = Object.is,
): T {
  const runtime = useActiveStreamsRuntime();
  const fallbackRecordRef = useRef<ConversationRuntimeRecord | null>(null);
  const resolveRecord = () => {
    const existing = runtime.store.getSnapshot().conversations.get(conversationId);
    if (existing) {
      return existing;
    }
    if (!fallbackRecordRef.current || fallbackRecordRef.current.conversationId !== conversationId) {
      fallbackRecordRef.current = runtime.store.getConversation(conversationId);
    }
    return fallbackRecordRef.current;
  };
  const cachedSelectionRef = useRef<T>(selector(resolveRecord()));

  const getSelection = () => {
    const nextSelection = selector(resolveRecord());
    if (isEqual(cachedSelectionRef.current, nextSelection)) {
      return cachedSelectionRef.current;
    }
    cachedSelectionRef.current = nextSelection;
    return nextSelection;
  };

  return useSyncExternalStore(
    runtime.store.subscribe,
    getSelection,
    getSelection,
  );
}

export type ConversationStreamMeta = {
  phase: StreamRenderSlice["phase"];
  runId: string | null;
  runMessageId: string | null;
  assistantMessageId: string | null;
  error: Error | null;
};

export function useConversationStream(conversationId: string): StreamRenderSlice {
  return useConversationSelector(conversationId, (record) => record.stream);
}

export function useConversationTranscript(conversationId: string): TranscriptSlice {
  return useConversationSelector(conversationId, (record) => record.transcript);
}

export function useConversationInputGate(conversationId: string): InputGateSlice {
  return useConversationSelector(conversationId, (record) => record.inputGate);
}

export function useConversationQueuedTurns(conversationId: string): QueuedTurn[] {
  return useConversationSelector(conversationId, (record) => record.queuedTurns);
}

export function useConversationStreamMeta(conversationId: string): ConversationStreamMeta {
  return useConversationSelector(
    conversationId,
    (record) => ({
      phase: record.stream.phase,
      runId: record.stream.runId,
      runMessageId: record.stream.runMessageId,
      assistantMessageId: record.stream.assistantMessageId,
      error: record.stream.error,
    }),
    shallowEqualObject,
  );
}

export function getActiveChatRuntimeStore(): ChatRuntimeStore | null {
  return activeStreamsRuntimeRef?.store ?? null;
}
