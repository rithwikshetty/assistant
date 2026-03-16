import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchConversationRuntimeMock,
  fetchConversationTimelinePageMock,
  cancelRunMock,
  createRunMock,
  runChatStreamTransportMock,
} = vi.hoisted(() => ({
  fetchConversationRuntimeMock: vi.fn(),
  fetchConversationTimelinePageMock: vi.fn(),
  cancelRunMock: vi.fn(),
  createRunMock: vi.fn(),
  runChatStreamTransportMock: vi.fn(),
}));

vi.mock("@/lib/api/chat", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/chat")>("@/lib/api/chat");
  return {
    ...actual,
    cancelRun: cancelRunMock,
    createRun: createRunMock,
    fetchConversationRuntime: fetchConversationRuntimeMock,
  };
});

vi.mock("@/lib/chat/runtime/timeline-repo", async () => {
  const actual = await vi.importActual<typeof import("@/lib/chat/runtime/timeline-repo")>("@/lib/chat/runtime/timeline-repo");
  return {
    ...actual,
    fetchConversationTimelinePage: fetchConversationTimelinePageMock,
  };
});

vi.mock("@/lib/chat/runtime/transport", () => ({
  runChatStreamTransport: runChatStreamTransportMock,
}));

import { createConversationRuntimeManager } from "./manager";
import { createChatRuntimeStore } from "./store";
import type { Message } from "./types";
import type { RequestUserInputPendingRequestResponse } from "@/lib/api/chat";

function installSessionStorageWindowStub(): void {
  const storage = new Map<string, string>();
  vi.stubGlobal("window", {
    sessionStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
      clear: () => {
        storage.clear();
      },
    },
  });
}

function resolveRequestId(message: Message | undefined): string | null {
  const payload = message?.metadata?.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const requestId = (payload as Record<string, unknown>).request_id;
  return typeof requestId === "string" && requestId.trim().length > 0 ? requestId : null;
}

function makePendingUserInputRequest(): RequestUserInputPendingRequestResponse {
  return {
    call_id: "call_1",
    tool_name: "request_user_input",
    request: {
      tool: "request_user_input",
      title: "Choose a direction",
      prompt: "Pick one option so Assist can continue.",
      questions: [
        {
          id: "q1",
          question: "Which one?",
          options: [
            { label: "A", description: "Take the first path." },
            { label: "B", description: "Take the second path." },
          ],
        },
      ],
    },
    result: {
      status: "pending",
      interaction_type: "user_input",
      request: {
        tool: "request_user_input",
        title: "Choose a direction",
        prompt: "Pick one option so Assist can continue.",
        questions: [
          {
            id: "q1",
            question: "Which one?",
            options: [
              { label: "A", description: "Take the first path." },
              { label: "B", description: "Take the second path." },
            ],
          },
        ],
      },
    },
  };
}

describe("conversation runtime manager", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    installSessionStorageWindowStub();
    fetchConversationRuntimeMock.mockReset();
    fetchConversationTimelinePageMock.mockReset();
    cancelRunMock.mockReset();
    createRunMock.mockReset();
    runChatStreamTransportMock.mockReset();
    fetchConversationTimelinePageMock.mockResolvedValue({
      messages: [],
      hasMore: false,
      nextCursor: null,
    });
    fetchConversationRuntimeMock.mockResolvedValue({
      status: "idle",
      active: false,
      run_id: null,
      run_message_id: null,
      status_label: null,
      assistant_message_id: null,
      resume_since_stream_event_id: 0,
      activity_cursor: 0,
      pending_requests: [],
      draft_text: "",
      activity_items: [],
    });
    createRunMock.mockResolvedValue({
      run_id: "run_1",
      user_message_id: "msg_1",
    });
    cancelRunMock.mockResolvedValue({
      run_id: "run_1",
      status: "cancelled",
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("clears stale runtime when a background conversation completes", () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_1");
    store.markStarted("conv_1", "msg_1", "run_1", "Thinking");
    store.applyStreamAction("conv_1", {
      type: "hydrate_runtime",
      phase: "streaming",
      statusLabel: "Thinking",
      draftText: "Still working",
      activityItems: [],
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
    });

    manager.unregisterConversation("conv_1");
    manager.handleLifecycleEvent({
      type: "stream_completed",
      conversation_id: "conv_1",
    });

    const record = store.getConversation("conv_1");
    expect(record.lifecycle.active).toBe(false);
    expect(record.lifecycle.completed).toBe(true);
    expect(record.stream.phase).toBe("idle");
    expect(record.stream.draftText).toBe("");
    expect(record.stream.activityItems).toEqual([]);

    manager.dispose();
    queryClient.clear();
  });

  it("does not bootstrap authoritative recovery for a local first-turn start", async () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_1");
    await Promise.resolve();
    fetchConversationRuntimeMock.mockClear();

    manager.markLocalStart("conv_1", "msg_1", "run_1", "Starting", {
      bootstrap: false,
    });
    await Promise.resolve();

    expect(fetchConversationRuntimeMock).not.toHaveBeenCalled();

    manager.dispose();
    queryClient.clear();
  });

  it("reuses a fresh warm transcript on register without forcing a latest-page refetch", async () => {
    const store = createChatRuntimeStore();
    store.replaceTranscript("conv_1", {
      messages: [
        {
          id: "msg_1",
          role: "assistant",
          content: [{ type: "text", text: "Latest" }],
          createdAt: new Date("2026-01-01T00:00:00.000Z"),
        },
      ],
      hasMore: false,
      nextCursor: null,
    });

    fetchConversationTimelinePageMock.mockClear();

    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_1");
    await Promise.resolve();

    expect(fetchConversationTimelinePageMock).not.toHaveBeenCalled();

    manager.dispose();
    queryClient.clear();
  });

  it("keeps a fresh local start visible when the first stream attach returns no_active_stream", async () => {
    runChatStreamTransportMock.mockImplementation(async (_conversationId: string, options: {
      onEvent: (event: {
        id: number;
        type: "no_active_stream";
        data: {
          reason: string;
          conversationId: string;
          runMessageId: string;
        };
      }) => Promise<void>;
    }) => {
      await options.onEvent({
        id: 1,
        type: "no_active_stream",
        data: {
          reason: "no_active_stream",
          conversationId: "conv_1",
          runMessageId: "msg_1",
        },
      });
    });

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_1");
    await Promise.resolve();

    await manager.sendMessage("conv_1", "Hello");

    const record = store.getConversation("conv_1");
    expect(record.lifecycle.active).toBe(true);
    expect(record.lifecycle.completed).toBe(false);
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.statusLabel).toBe("Starting");

    manager.dispose();
    queryClient.clear();
  });

  it("retries with authoritative runtime after an early no_active_stream on first attach", async () => {
    vi.useFakeTimers();
    try {
      const releaseTransportRef: { current: (() => void) | null } = { current: null };
      runChatStreamTransportMock
        .mockImplementationOnce(async (_conversationId: string, options: {
          onEvent: (event: {
            id: number;
            type: "no_active_stream";
            data: {
              reason: string;
              conversationId: string;
              runMessageId: string;
            };
          }) => Promise<void>;
        }) => {
          await options.onEvent({
            id: 1,
            type: "no_active_stream",
            data: {
              reason: "no_active_stream",
              conversationId: "conv_1",
              runMessageId: "msg_1",
            },
          });
        })
        .mockImplementationOnce(async () => {
          await new Promise<void>((resolve) => {
            releaseTransportRef.current = resolve;
          });
        });

      fetchConversationRuntimeMock.mockResolvedValue({
        status: "running",
        active: true,
        run_id: "run_1",
        run_message_id: "msg_1",
        status_label: "Authoritative step",
        assistant_message_id: "assist_1",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        draft_text: "",
        activity_items: [],
      });

      const store = createChatRuntimeStore();
      const queryClient = new QueryClient();
      const manager = createConversationRuntimeManager({
        store,
        queryClient,
      });

      manager.registerConversation("conv_1");
      await Promise.resolve();

      const sendPromise = manager.sendMessage("conv_1", "Hello");
      await Promise.resolve();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(150);

      const record = store.getConversation("conv_1");
      expect(fetchConversationRuntimeMock).toHaveBeenCalled();
      expect(runChatStreamTransportMock).toHaveBeenCalledTimes(2);
      expect(record.stream.phase).toBe("streaming");
      expect(record.stream.statusLabel).toBe("Authoritative step");
      expect(record.lifecycle.active).toBe(true);

      releaseTransportRef.current?.();
      await sendPromise;

      manager.dispose();
      queryClient.clear();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reprojects optimistic transcript tool results from activity items", () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    const message: Message = {
      id: "assist_1",
      role: "assistant",
      content: [{ type: "text", text: "Final answer", phase: "final" }],
      activityItems: [
        {
          id: "activity_1",
          runId: "run_1",
          itemKey: "tool:call_1",
          kind: "tool",
          status: "running",
          title: "Project files",
          summary: null,
          sequence: 1,
          payload: {
            tool_call_id: "call_1",
            tool_name: "retrieval_project_files",
          },
          createdAt: "2026-03-10T00:00:00Z",
          updatedAt: "2026-03-10T00:00:00Z",
        },
      ],
      createdAt: new Date("2026-03-10T00:00:00Z"),
      metadata: {
        payload: {
          text: "Final answer",
        },
        activity_item_count: 1,
      },
    };

    store.replaceTranscript("conv_1", {
      messages: [message],
      hasMore: false,
      nextCursor: null,
    });

    manager.applyOptimisticToolResult("conv_1", "assist_1", "call_1", {
      content: "Found project references",
      sources: [],
    });

    const updated = store.getConversation("conv_1").transcript.messages[0];
    expect(updated.activityItems).toHaveLength(1);
    expect(updated.activityItems?.[0]).toMatchObject({
      payload: {
        tool_call_id: "call_1",
        result: {
          content: "Found project references",
          sources: [],
        },
      },
    });
    expect(updated.content).toMatchObject([
      {
        type: "tool-call",
        toolCallId: "call_1",
        result: {
          content: "Found project references",
          sources: [],
        },
      },
      {
        type: "text",
        text: "Final answer",
        phase: "final",
      },
    ]);
    expect(updated.metadata?.activity_item_count).toBe(1);

    manager.dispose();
    queryClient.clear();
  });

  it("hydrates running state from authoritative runtime after runtime_update instead of mutating transport payload inline", async () => {
    vi.useFakeTimers();
    try {
      const releaseTransportRef: { current: (() => void) | null } = { current: null };
      runChatStreamTransportMock.mockImplementation(async (_conversationId: string, options: {
        onEvent: (event: {
          id: number;
          type: "runtime_update";
          data: {
            statusLabel: string;
          };
        }) => Promise<void>;
      }) => {
        await options.onEvent({
          id: 1,
          type: "runtime_update",
          data: {
            statusLabel: "Generating response",
          },
        });
        await new Promise<void>((resolve) => {
          releaseTransportRef.current = resolve;
        });
      });
      fetchConversationRuntimeMock.mockResolvedValue({
        status: "running",
        active: true,
        run_id: "run_1",
        run_message_id: "msg_1",
        status_label: "Authoritative step",
        assistant_message_id: "assist_1",
        resume_since_stream_event_id: 7,
        activity_cursor: 1,
        pending_requests: [],
        draft_text: "authoritative runtime text",
        activity_items: [],
      });

      const store = createChatRuntimeStore();
      const queryClient = new QueryClient();
      const manager = createConversationRuntimeManager({
        store,
        queryClient,
      });

      manager.registerConversation("conv_1");
      await Promise.resolve();
      const sendPromise = manager.sendMessage("conv_1", "Hello");
      await Promise.resolve();
      await Promise.resolve();

      let record = store.getConversation("conv_1");
      expect(record.stream.draftText).toBe("");
      expect(record.stream.statusLabel).toBe("Starting");

      await vi.advanceTimersByTimeAsync(300);

      record = store.getConversation("conv_1");
      expect(fetchConversationRuntimeMock).toHaveBeenCalled();
      expect(record.stream.draftText).toBe("authoritative runtime text");
      expect(record.stream.statusLabel).toBe("Authoritative step");

      if (releaseTransportRef.current) {
        releaseTransportRef.current();
      }
      await sendPromise;

      manager.dispose();
      queryClient.clear();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rechecks authoritative runtime after a WS_RELAY during bootstrap reconnect", async () => {
    vi.useFakeTimers();
    try {
      runChatStreamTransportMock
        .mockImplementationOnce(async (_conversationId: string, options: {
          onEvent: (event: {
            id: number;
            type: "error";
            data: {
              message: string;
              code: string;
            };
          }) => Promise<void>;
        }) => {
          await options.onEvent({
            id: 1,
            type: "error",
            data: {
              message: "WebSocket stream relay failed",
              code: "WS_RELAY",
            },
          });
        })
        .mockResolvedValueOnce(undefined);

      fetchConversationRuntimeMock
        .mockResolvedValueOnce({
          status: "running",
          active: true,
          run_id: "run_1",
          run_message_id: "msg_1",
          status_label: "Authoritative step",
          assistant_message_id: "assist_1",
          resume_since_stream_event_id: 7,
          activity_cursor: 1,
          pending_requests: [],
          draft_text: "authoritative runtime text",
          activity_items: [],
        })
        .mockResolvedValueOnce({
          status: "running",
          active: true,
          run_id: "run_1",
          run_message_id: "msg_1",
          status_label: "Recovered step",
          assistant_message_id: "assist_1",
          resume_since_stream_event_id: 8,
          activity_cursor: 1,
          pending_requests: [],
          draft_text: "recovered runtime text",
          activity_items: [],
        });

      const store = createChatRuntimeStore();
      const queryClient = new QueryClient();
      const manager = createConversationRuntimeManager({
        store,
        queryClient,
      });

      manager.registerConversation("conv_1");
      await Promise.resolve();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(300);

      expect(fetchConversationRuntimeMock).toHaveBeenCalledTimes(2);
      expect(runChatStreamTransportMock).toHaveBeenCalledTimes(2);

      const record = store.getConversation("conv_1");
      expect(record.stream.phase).toBe("streaming");
      expect(record.stream.statusLabel).toBe("Recovered step");
      expect(record.stream.draftText).toBe("recovered runtime text");

      manager.dispose();
      queryClient.clear();
    } finally {
      vi.useRealTimers();
    }
  });

  it("retains a fresh local first-turn shell after early transport progress when authoritative runtime is still idle", async () => {
    vi.useFakeTimers();
    try {
      const releaseTransportRef: { current: (() => void) | null } = { current: null };
      runChatStreamTransportMock.mockImplementation(async (_conversationId: string, options: {
        onEvent: (event: {
          id: number;
          type: "runtime_update";
          data: {
            statusLabel: string;
          };
        }) => Promise<void>;
      }) => {
        await options.onEvent({
          id: 1,
          type: "runtime_update",
          data: {
            statusLabel: "Generating response",
          },
        });
        await new Promise<void>((resolve) => {
          releaseTransportRef.current = resolve;
        });
      });

      fetchConversationRuntimeMock.mockResolvedValue({
        status: "idle",
        active: false,
        run_id: null,
        run_message_id: null,
        status_label: null,
        assistant_message_id: null,
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        draft_text: "",
        activity_items: [],
      });

      const store = createChatRuntimeStore();
      const queryClient = new QueryClient();
      const manager = createConversationRuntimeManager({
        store,
        queryClient,
      });

      manager.registerConversation("conv_1");
      await Promise.resolve();
      const sendPromise = manager.sendMessage("conv_1", "Hello");
      await Promise.resolve();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(300);

      const record = store.getConversation("conv_1");
      expect(fetchConversationRuntimeMock).toHaveBeenCalled();
      expect(record.stream.phase).toBe("streaming");
      expect(record.stream.statusLabel).toBe("Starting");
      expect(record.lifecycle.active).toBe(true);
      expect(record.lifecycle.completed).toBe(false);

      releaseTransportRef.current?.();
      await sendPromise;

      manager.dispose();
      queryClient.clear();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the hydrated running shell visible when refresh bootstrap hits a transient no_active_stream", async () => {
    fetchConversationRuntimeMock.mockResolvedValue({
      status: "running",
      active: true,
      run_id: "run_refresh",
      run_message_id: "msg_refresh",
      status_label: "Generating response",
      assistant_message_id: "assist_refresh",
      resume_since_stream_event_id: 7,
      activity_cursor: 7,
      pending_requests: [],
      draft_text: "Recovered draft",
      activity_items: [],
      live_message: {
        id: "assist_refresh",
        seq: 8,
        run_id: "run_refresh",
        type: "assistant_message_partial",
        actor: "assistant",
        created_at: "2026-03-11T00:00:00.000Z",
        role: "assistant",
        text: "Recovered draft",
        activity_items: [],
        payload: {
          text: "Recovered draft",
          status: "running",
        },
      },
    });

    runChatStreamTransportMock.mockImplementation(async (_conversationId: string, options: {
      onEvent: (event: {
        id: number;
        type: "no_active_stream";
        data: {
          reason: string;
          conversationId: string;
          runMessageId: string;
        };
      }) => Promise<void>;
    }) => {
      await options.onEvent({
        id: 8,
        type: "no_active_stream",
        data: {
          reason: "no_active_stream",
          conversationId: "conv_refresh",
          runMessageId: "msg_refresh",
        },
      });
    });

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_refresh");
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    const record = store.getConversation("conv_refresh");
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.runId).toBe("run_refresh");
    expect(record.stream.runMessageId).toBe("msg_refresh");
    expect(record.stream.draftText).toBe("Recovered draft");
    expect(record.stream.liveMessage?.id).toBe("assist_refresh");

    manager.dispose();
    queryClient.clear();
  });

  it("preserves an optimistic first message across the initial route transcript fetch until the persisted row exists", async () => {
    let resolveCreateRun: ((value: { run_id: string; user_message_id: string }) => void) | null = null;
    createRunMock.mockImplementation(() => new Promise((resolve) => {
      resolveCreateRun = resolve;
    }));

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    const sendPromise = manager.sendMessage("conv_new", "Hello");
    await Promise.resolve();

    let record = store.getConversation("conv_new");
    expect(record.transcript.messages).toHaveLength(1);
    expect(record.transcript.messages[0]).toMatchObject({
      id: expect.stringMatching(/^temp_/),
      role: "user",
      status: "pending",
      content: [{ type: "text", text: "Hello" }],
    });

    const requestId = resolveRequestId(record.transcript.messages[0]);
    expect(requestId).toEqual(expect.any(String));

    fetchConversationTimelinePageMock.mockResolvedValueOnce({
      messages: [],
      hasMore: false,
      nextCursor: null,
    });

    manager.registerConversation("conv_new");
    await Promise.resolve();
    await Promise.resolve();

    record = store.getConversation("conv_new");
    expect(fetchConversationTimelinePageMock).toHaveBeenCalledWith({
      conversationId: "conv_new",
      limit: 100,
      cursor: null,
    });
    expect(record.transcript.messages).toHaveLength(1);
    expect(record.transcript.messages[0]).toMatchObject({
      role: "user",
      status: "pending",
      metadata: {
        payload: {
          request_id: requestId,
        },
      },
    });

    if (!resolveCreateRun) {
      throw new Error("createRun resolver was not captured");
    }
    const finalizeCreateRun = resolveCreateRun as (value: {
      run_id: string;
      user_message_id: string;
    }) => void;
    finalizeCreateRun({ run_id: "run_1", user_message_id: "msg_1" });
    await sendPromise;

    record = store.getConversation("conv_new");
    expect(record.transcript.messages).toHaveLength(1);
    expect(record.transcript.messages[0].id).toBe("msg_1");

    fetchConversationTimelinePageMock.mockResolvedValueOnce({
      messages: [
        {
          id: "msg_1",
          role: "user",
          content: [{ type: "text", text: "Hello" }],
          createdAt: new Date("2026-03-11T00:00:00.000Z"),
          metadata: {
            event_type: "user_message",
            payload: {
              text: "Hello",
              request_id: requestId,
            },
            run_id: "run_1",
            activity_item_count: 0,
            stream_checkpoint_event_id: null,
          },
          status: null,
        },
      ],
      hasMore: false,
      nextCursor: null,
    });

    await manager.refreshConversation("conv_new");

    record = store.getConversation("conv_new");
    expect(record.transcript.messages).toHaveLength(1);
    expect(record.transcript.messages[0]).toMatchObject({
      id: "msg_1",
      role: "user",
      metadata: {
        payload: {
          request_id: requestId,
        },
      },
    });

    manager.dispose();
    queryClient.clear();
  });

  it("attaches live transport immediately when a queued turn is promoted", async () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_queued");
    store.noteQueuedTurn("conv_queued", {
      queuePosition: 1,
      runId: "run_queued",
      userMessageId: "msg_queued",
      blockedByRunId: "run_active",
      createdAt: "2026-01-01T00:00:00.000Z",
    });
    store.applyStreamAction("conv_queued", {
      type: "hydrate_runtime",
      phase: "starting",
      statusLabel: "Queued",
      draftText: "",
      activityItems: [],
      runId: "run_queued",
      runMessageId: "msg_queued",
      assistantMessageId: null,
    });

    manager.handleLifecycleEvent({
      type: "stream_started",
      conversation_id: "conv_queued",
      run_id: "run_queued",
      user_message_id: "msg_queued",
      current_step: "Starting",
    });
    await Promise.resolve();

    expect(runChatStreamTransportMock).toHaveBeenCalledWith(
      "conv_queued",
      expect.objectContaining({
        sinceStreamEventId: 0,
        runMessageId: "msg_queued",
      }),
    );

    const record = store.getConversation("conv_queued");
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.statusLabel).toBe("Starting");
    expect(record.queuedTurns).toEqual([]);

    manager.dispose();
    queryClient.clear();
  });

  it("stops the active run without preserving queued follow-ups locally", async () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    store.markStarted("conv_stop", "msg_active", "run_active", "Thinking");
    store.noteQueuedTurn("conv_stop", {
      queuePosition: 1,
      runId: "run_queued",
      userMessageId: "msg_queued",
      blockedByRunId: "run_active",
      createdAt: "2026-03-13T00:00:00.000Z",
      text: "Queued follow-up",
    });
    store.applyStreamAction("conv_stop", {
      type: "hydrate_runtime",
      phase: "streaming",
      statusLabel: "Thinking",
      draftText: "Working",
      activityItems: [],
      runId: "run_active",
      runMessageId: "msg_active",
      assistantMessageId: "assist_active",
    });

    await manager.stopActiveRun("conv_stop");

    expect(cancelRunMock).toHaveBeenCalledWith("run_active");
    const record = store.getConversation("conv_stop");
    expect(record.queuedTurns).toEqual([]);
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.runId).toBe("run_active");

    manager.dispose();
    queryClient.clear();
  });

  it("reattaches to the promoted queued run after refresh recovery", async () => {
    fetchConversationRuntimeMock.mockResolvedValue({
      status: "running",
      active: true,
      run_id: "run_active",
      run_message_id: "msg_active",
      status_label: "Thinking",
      assistant_message_id: "assist_active",
      resume_since_stream_event_id: 5,
      activity_cursor: 5,
      pending_requests: [],
      draft_text: "Recovered active draft",
      activity_items: [],
      queued_turns: [
        {
          queue_position: 1,
          run_id: "run_queued",
          user_message_id: "msg_queued",
          blocked_by_run_id: "run_active",
          created_at: "2026-03-13T00:00:00.000Z",
        },
      ],
    });

    runChatStreamTransportMock
      .mockImplementationOnce(async (_conversationId: string, options: {
        abortSignal: AbortSignal;
      }) => {
        await new Promise<void>((resolve) => {
          options.abortSignal.addEventListener("abort", () => resolve(), { once: true });
        });
      })
      .mockResolvedValueOnce(undefined);

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_refresh_queue");
    await Promise.resolve();
    await Promise.resolve();

    expect(runChatStreamTransportMock).toHaveBeenCalledTimes(1);
    expect(runChatStreamTransportMock).toHaveBeenNthCalledWith(
      1,
      "conv_refresh_queue",
      expect.objectContaining({
        runMessageId: "msg_active",
        sinceStreamEventId: 5,
      }),
    );

    manager.handleLifecycleEvent({
      type: "stream_started",
      conversation_id: "conv_refresh_queue",
      run_id: "run_queued",
      user_message_id: "msg_queued",
      current_step: "Starting",
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(runChatStreamTransportMock).toHaveBeenCalledTimes(2);
    expect(runChatStreamTransportMock).toHaveBeenNthCalledWith(
      2,
      "conv_refresh_queue",
      expect.objectContaining({
        sinceStreamEventId: 0,
        runMessageId: "msg_queued",
      }),
    );

    const record = store.getConversation("conv_refresh_queue");
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.runId).toBe("run_queued");
    expect(record.stream.runMessageId).toBe("msg_queued");
    expect(record.stream.assistantMessageId).toBeNull();
    expect(record.queuedTurns).toEqual([]);

    manager.dispose();
    queryClient.clear();
  });

  it("hydrates paused runtime when a lifecycle pause arrives before a page refresh", async () => {
    fetchConversationRuntimeMock.mockResolvedValue({
      status: "paused",
      active: true,
      run_id: "run_pause",
      run_message_id: "msg_pause",
      status_label: "Waiting for your input",
      assistant_message_id: "assist_pause",
      resume_since_stream_event_id: 3,
      activity_cursor: 3,
      pending_requests: [makePendingUserInputRequest()],
      draft_text: "Both work. I’ll pause and let you choose the direction.",
      activity_items: [],
    });

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_pause");
    store.applyStreamAction("conv_pause", {
      type: "hydrate_runtime",
      phase: "starting",
      statusLabel: "Starting",
      draftText: "",
      activityItems: [],
      runId: "run_pause",
      runMessageId: "msg_pause",
      assistantMessageId: null,
    });

    manager.handleLifecycleEvent({
      type: "stream_paused",
      conversation_id: "conv_pause",
    });
    await Promise.resolve();
    await Promise.resolve();

    const record = store.getConversation("conv_pause");
    expect(fetchConversationRuntimeMock).toHaveBeenCalled();
    expect(record.stream.phase).toBe("paused_for_input");
    expect(record.stream.statusLabel).toBe("Waiting for your input");
    expect(record.inputGate.isPausedForInput).toBe(true);
    expect(record.inputGate.pausedPayload?.requests).toHaveLength(1);

    manager.dispose();
    queryClient.clear();
  });

  it("uses authoritative recovery after interactive submission instead of locally resuming stale paused state", async () => {
    fetchConversationRuntimeMock.mockResolvedValue({
      status: "running",
      active: true,
      run_id: "run_resume",
      run_message_id: "msg_resume",
      status_label: "Resuming",
      assistant_message_id: "assist_resume",
      resume_since_stream_event_id: 0,
      activity_cursor: 0,
      pending_requests: [],
      draft_text: "Resuming after your selection.",
      activity_items: [],
    });

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_resume");
    store.applyStreamAction("conv_resume", {
      type: "hydrate_runtime",
      phase: "paused_for_input",
      statusLabel: "Waiting for your input",
      draftText: "Choose one path",
      activityItems: [],
      runId: "run_resume",
      runMessageId: "msg_resume",
      assistantMessageId: "assist_resume",
    });
    store.setInputGate("conv_resume", {
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_resume",
        runId: "run_resume",
        messageId: "assist_resume",
        requests: [
          {
            callId: "call_1",
            toolName: "request_user_input",
            request: makePendingUserInputRequest().request,
            result: makePendingUserInputRequest().result,
          },
        ],
      },
    });

    await manager.handleInteractiveToolSubmitted("conv_resume");

    const record = store.getConversation("conv_resume");
    expect(fetchConversationRuntimeMock).toHaveBeenCalled();
    expect(record.inputGate.isPausedForInput).toBe(false);
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.statusLabel).toBe("Resuming");
    expect(runChatStreamTransportMock).toHaveBeenCalledWith(
      "conv_resume",
      expect.objectContaining({
        sinceStreamEventId: 0,
        runMessageId: "msg_resume",
      }),
    );

    manager.dispose();
    queryClient.clear();
  });

  it("restores paused input state when interactive recovery cannot prove the run resumed", async () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_recover_pause");
    await Promise.resolve();
    fetchConversationRuntimeMock.mockClear();
    fetchConversationRuntimeMock.mockRejectedValueOnce(new Error("runtime timed out"));
    store.applyStreamAction("conv_recover_pause", {
      type: "hydrate_runtime",
      phase: "paused_for_input",
      statusLabel: "Waiting for your input",
      draftText: "Choose one path",
      activityItems: [],
      runId: "run_pause",
      runMessageId: "msg_pause",
      assistantMessageId: "assist_pause",
    });
    store.setInputGate("conv_recover_pause", {
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_recover_pause",
        runId: "run_pause",
        messageId: "assist_pause",
        requests: [
          {
            callId: "call_1",
            toolName: "request_user_input",
            request: makePendingUserInputRequest().request,
            result: makePendingUserInputRequest().result,
          },
        ],
      },
    });

    await manager.handleInteractiveToolSubmitted("conv_recover_pause");

    const record = store.getConversation("conv_recover_pause");
    expect(record.stream.phase).toBe("paused_for_input");
    expect(record.inputGate.isPausedForInput).toBe(true);
    expect(record.inputGate.pausedPayload?.requests).toHaveLength(1);

    manager.dispose();
    queryClient.clear();
  });

  it("forces a fresh authoritative recovery after interactive submit instead of reusing a stale paused recovery", async () => {
    let resolvePausedRecovery: ((value: Record<string, unknown>) => void) | undefined;
    fetchConversationRuntimeMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePausedRecovery = resolve as (value: Record<string, unknown>) => void;
        }),
    );

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_resume_fresh");
    await Promise.resolve();
    fetchConversationRuntimeMock
      .mockResolvedValueOnce({
        status: "running",
        active: true,
        run_id: "run_resume_fresh",
        run_message_id: "msg_resume_fresh",
        status_label: "Resuming",
        assistant_message_id: "assist_resume_fresh",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        draft_text: "Resuming after your selection.",
        activity_items: [],
      });

    store.applyStreamAction("conv_resume_fresh", {
      type: "hydrate_runtime",
      phase: "paused_for_input",
      statusLabel: "Waiting for your input",
      draftText: "Choose one path",
      activityItems: [],
      runId: "run_resume_fresh",
      runMessageId: "msg_resume_fresh",
      assistantMessageId: "assist_resume_fresh",
    });
    store.setInputGate("conv_resume_fresh", {
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_resume_fresh",
        runId: "run_resume_fresh",
        messageId: "assist_resume_fresh",
        requests: [
          {
            callId: "call_1",
            toolName: "request_user_input",
            request: makePendingUserInputRequest().request,
            result: makePendingUserInputRequest().result,
          },
        ],
      },
    });

    const submissionPromise = manager.handleInteractiveToolSubmitted("conv_resume_fresh");
    await Promise.resolve();

    expect(fetchConversationRuntimeMock).toHaveBeenCalledTimes(2);
    const afterSubmit = store.getConversation("conv_resume_fresh");
    expect(afterSubmit.inputGate.isPausedForInput).toBe(false);
    expect(afterSubmit.stream.statusLabel).toBe("Resuming");

    resolvePausedRecovery?.({
      status: "paused",
      active: true,
      run_id: "run_resume_fresh",
      run_message_id: "msg_resume_fresh",
      status_label: "Waiting for your input",
      assistant_message_id: "assist_resume_fresh",
      resume_since_stream_event_id: 0,
      activity_cursor: 0,
      pending_requests: [makePendingUserInputRequest()],
      draft_text: "Choose one path",
      activity_items: [],
    });

    await submissionPromise;

    const record = store.getConversation("conv_resume_fresh");
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.statusLabel).toBe("Resuming");
    expect(runChatStreamTransportMock).toHaveBeenCalledWith(
      "conv_resume_fresh",
      expect.objectContaining({
        sinceStreamEventId: 0,
        runMessageId: "msg_resume_fresh",
      }),
    );

    manager.dispose();
    queryClient.clear();
  });

  it("reattaches immediately when a paused run emits stream_started after interactive submit recovery went stale", async () => {
    let resolveRuntime: ((value: Record<string, unknown>) => void) | undefined;
    fetchConversationRuntimeMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveRuntime = resolve as (value: Record<string, unknown>) => void;
        }),
    );

    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_resume_late");
    store.applyStreamAction("conv_resume_late", {
      type: "hydrate_runtime",
      phase: "paused_for_input",
      statusLabel: "Waiting for your input",
      draftText: "Choose one path",
      activityItems: [],
      runId: "run_resume_late",
      runMessageId: "msg_resume_late",
      assistantMessageId: "assist_resume_late",
    });
    store.setInputGate("conv_resume_late", {
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_resume_late",
        runId: "run_resume_late",
        messageId: "assist_resume_late",
        requests: [
          {
            callId: "call_1",
            toolName: "request_user_input",
            request: makePendingUserInputRequest().request,
            result: makePendingUserInputRequest().result,
          },
        ],
      },
    });

    const submissionPromise = manager.handleInteractiveToolSubmitted("conv_resume_late");

    const afterSubmit = store.getConversation("conv_resume_late");
    expect(afterSubmit.inputGate.isPausedForInput).toBe(false);

    manager.handleLifecycleEvent({
      type: "stream_started",
      conversation_id: "conv_resume_late",
      run_id: "run_resume_late",
      user_message_id: "msg_resume_late",
      current_step: "Resuming",
    });

    resolveRuntime?.({
      status: "paused",
      active: true,
      run_id: "run_resume_late",
      run_message_id: "msg_resume_late",
      status_label: "Waiting for your input",
      assistant_message_id: "assist_resume_late",
      resume_since_stream_event_id: 0,
      activity_cursor: 0,
      pending_requests: [],
      draft_text: "Choose one path",
      activity_items: [],
    });
    await submissionPromise;

    const record = store.getConversation("conv_resume_late");
    expect(runChatStreamTransportMock).toHaveBeenCalledWith(
      "conv_resume_late",
      expect.objectContaining({
        sinceStreamEventId: 0,
        runMessageId: "msg_resume_late",
      }),
    );
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.statusLabel).toBe("Resuming");
    expect(record.inputGate.isPausedForInput).toBe(false);

    manager.dispose();
    queryClient.clear();
  });

  it("ignores queued-promotion lifecycle events for a different queued run", async () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    manager.registerConversation("conv_queued_mismatch");
    store.applyStreamAction("conv_queued_mismatch", {
      type: "hydrate_runtime",
      phase: "starting",
      statusLabel: "Queued",
      draftText: "",
      activityItems: [],
      runId: "run_expected",
      runMessageId: "msg_expected",
      assistantMessageId: null,
    });

    manager.handleLifecycleEvent({
      type: "stream_started",
      conversation_id: "conv_queued_mismatch",
      run_id: "run_stale",
      user_message_id: "msg_stale",
      current_step: "Starting",
    });
    await Promise.resolve();

    const record = store.getConversation("conv_queued_mismatch");
    expect(runChatStreamTransportMock).not.toHaveBeenCalled();
    expect(record.stream.phase).toBe("starting");
    expect(record.stream.statusLabel).toBe("Queued");
    expect(record.stream.runId).toBe("run_expected");
    expect(record.stream.runMessageId).toBe("msg_expected");

    manager.dispose();
    queryClient.clear();
  });

  it("aborts the previous transport before a follow-up createRun resolves from completing", async () => {
    const store = createChatRuntimeStore();
    const queryClient = new QueryClient();
    const manager = createConversationRuntimeManager({
      store,
      queryClient,
    });

    const firstTransportRef: {
      current: null | {
        abortSignal: AbortSignal;
        onEvent: (event: { id: number; type: "done"; data: { status: "completed" } }) => Promise<void>;
      };
    } = { current: null };
    const secondRunRef: {
      current: undefined | ((value: { run_id: string; user_message_id: string }) => void);
    } = { current: undefined };

    createRunMock
      .mockResolvedValueOnce({
        run_id: "run_old",
        user_message_id: "msg_old",
      })
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          secondRunRef.current = resolve as (value: { run_id: string; user_message_id: string }) => void;
        }),
      );

    runChatStreamTransportMock
      .mockImplementationOnce(async (_conversationId: string, options: {
        abortSignal: AbortSignal;
        onEvent: (event: { id: number; type: "done"; data: { status: "completed" } }) => Promise<void>;
      }) => {
        firstTransportRef.current = options;
        await new Promise<void>((resolve) => {
          options.abortSignal.addEventListener("abort", () => resolve(), { once: true });
        });
      })
      .mockResolvedValueOnce(undefined);

    manager.registerConversation("conv_overlap");
    await Promise.resolve();

    const firstSendPromise = manager.sendMessage("conv_overlap", "First");
    await Promise.resolve();
    await Promise.resolve();

    expect(firstTransportRef.current).not.toBeNull();

    store.applyStreamAction("conv_overlap", {
      type: "set_phase",
      phase: "completing",
    });

    const secondSendPromise = manager.sendMessage("conv_overlap", "Second");
    await Promise.resolve();

    expect(firstTransportRef.current).not.toBeNull();
    const capturedFirstTransport = firstTransportRef.current;
    if (!capturedFirstTransport) {
      throw new Error("expected the first transport to be captured");
    }
    expect(capturedFirstTransport.abortSignal.aborted).toBe(true);

    await capturedFirstTransport.onEvent({
      id: 99,
      type: "done",
      data: { status: "completed" },
    });

    const overlapRecord = store.getConversation("conv_overlap");
    expect(overlapRecord.stream.phase).toBe("starting");

    const completeSecondRun = secondRunRef.current;
    if (!completeSecondRun) {
      throw new Error("expected the second run promise to be controllable");
    }
    completeSecondRun({
      run_id: "run_new",
      user_message_id: "msg_new",
    });

    await secondSendPromise;
    await firstSendPromise;

    manager.dispose();
    queryClient.clear();
  });
});
