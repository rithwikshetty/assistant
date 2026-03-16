import { describe, expect, it } from "vitest";

import { createChatRuntimeStore } from "./store";
import type { Message } from "./types";

function makeMessage(id: string, role: Message["role"], text: string): Message {
  return {
    id,
    role,
    content: [{ type: "text", text }],
    createdAt: new Date("2026-01-01T00:00:00.000Z"),
  };
}

function makePendingOptimisticUserMessage(id: string, text: string, requestId: string): Message {
  return {
    id,
    role: "user",
    content: [{ type: "text", text }],
    createdAt: new Date("2026-01-01T00:00:00.000Z"),
    status: "pending",
    metadata: {
      event_type: "user_message",
      payload: {
        text,
        request_id: requestId,
      },
      run_id: null,
      activity_item_count: 0,
      stream_checkpoint_event_id: null,
    },
  };
}

describe("chat runtime store", () => {
  it("tracks lifecycle and runtime state per conversation", () => {
    const store = createChatRuntimeStore();

    store.markStarted("conv_1", "msg_1", "run_1", "Thinking");
    store.applyStreamAction("conv_1", {
      type: "hydrate_runtime",
      phase: "streaming",
      statusLabel: "Thinking",
      draftText: "Hello",
      activityItems: [
        {
          id: "activity_1",
          runId: "run_1",
          itemKey: "tool:call_1",
          kind: "tool",
          status: "running",
          title: "web search",
          summary: null,
          sequence: 1,
          payload: { tool_call_id: "call_1", tool_name: "retrieval_web_search" },
          createdAt: "2026-01-01T00:00:00.000Z",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      ],
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
    });
    store.noteTransportProgress("conv_1", {
      eventId: 42,
      atMs: 1_000,
    });

    const record = store.getConversation("conv_1");
    expect(record.lifecycle).toEqual({
      active: true,
      completed: false,
      runId: "run_1",
      runMessageId: "msg_1",
      currentStep: "Thinking",
    });
    expect(record.stream.phase).toBe("streaming");
    expect(record.stream.draftText).toBe("Hello");
    expect(record.stream.activityItems).toEqual([
      expect.objectContaining({ itemKey: "tool:call_1" }),
    ]);
    expect(record.stream.content).toMatchObject([
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", text: "Hello", phase: "final" },
    ]);
    expect(record.stream.assistantMessageId).toBe("assist_1");
    expect(record.lastEventId).toBe(42);
    expect(record.updatedAtMs).toBe(1_000);
  });

  it("replaces active lifecycle snapshot without losing completed markers for other conversations", () => {
    const store = createChatRuntimeStore();

    store.markCompleted("conv_done");
    store.markStarted("conv_live", "msg_1", "run_1", "Working");
    store.replaceActiveStreams([
      {
        conversationId: "conv_fresh",
        runMessageId: "msg_2",
        runId: "run_2",
        currentStep: "Searching",
      },
    ]);

    expect(store.getConversation("conv_live").lifecycle.active).toBe(false);
    expect(store.getConversation("conv_done").lifecycle.completed).toBe(true);
    expect(store.getConversation("conv_fresh").lifecycle).toEqual({
      active: true,
      completed: false,
      runId: "run_2",
      runMessageId: "msg_2",
      currentStep: "Searching",
    });
  });

  it("clears runtime state while preserving a completion marker when requested", () => {
    const store = createChatRuntimeStore();

    store.markStarted("conv_1", "msg_1", "run_1", "Thinking");
    store.applyStreamAction("conv_1", {
      type: "hydrate_runtime",
      phase: "streaming",
      statusLabel: "Thinking",
      draftText: "Working",
      activityItems: [],
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
    });
    store.clearRuntime("conv_1", { preserveCompleted: false });
    store.markCompleted("conv_1");

    const record = store.getConversation("conv_1");
    expect(record.lifecycle.completed).toBe(true);
    expect(record.lifecycle.active).toBe(false);
    expect(record.stream.phase).toBe("idle");
    expect(record.stream.draftText).toBe("");
    expect(record.stream.activityItems).toEqual([]);
    expect(record.stream.assistantMessageId).toBeNull();
  });

  it("stores transcript pages and older-message prepends in the runtime store", () => {
    const store = createChatRuntimeStore();

    store.setTranscriptLoading("conv_1", { isLoadingInitial: true });
    store.replaceTranscript("conv_1", {
      messages: [makeMessage("msg_2", "assistant", "Latest")],
      hasMore: true,
      nextCursor: "cursor_older",
    });
    store.prependTranscript("conv_1", {
      messages: [makeMessage("msg_1", "user", "Earlier")],
      hasMore: false,
      nextCursor: null,
    });

    const record = store.getConversation("conv_1");
    expect(record.transcript.initialized).toBe(true);
    expect(record.transcript.isLoadingInitial).toBe(false);
    expect(record.transcript.hasMore).toBe(false);
    expect(record.transcript.nextCursor).toBeNull();
    expect(record.transcript.lastSyncedAtMs).toBeGreaterThan(0);
    expect(record.transcript.messages.map((message) => message.id)).toEqual(["msg_1", "msg_2"]);
  });

  it("does not treat older-page prepends as a latest-page resync", () => {
    const store = createChatRuntimeStore();

    store.replaceTranscript("conv_1", {
      messages: [makeMessage("msg_2", "assistant", "Latest")],
      hasMore: true,
      nextCursor: "cursor_older",
    });
    const firstSyncedAtMs = store.getConversation("conv_1").transcript.lastSyncedAtMs;

    store.prependTranscript("conv_1", {
      messages: [makeMessage("msg_1", "user", "Earlier")],
      hasMore: false,
      nextCursor: null,
    });

    const record = store.getConversation("conv_1");
    expect(record.transcript.lastSyncedAtMs).toBe(firstSyncedAtMs);
  });

  it("preserves a pending optimistic user message when the latest transcript fetch is still missing it", () => {
    const store = createChatRuntimeStore();

    store.updateTranscriptMessages("conv_1", [
      makePendingOptimisticUserMessage("temp_1", "Hello", "req_1"),
    ]);
    store.replaceTranscript("conv_1", {
      messages: [],
      hasMore: false,
      nextCursor: null,
    });

    const record = store.getConversation("conv_1");
    expect(record.transcript.messages).toHaveLength(1);
    expect(record.transcript.messages[0]).toMatchObject({
      id: "temp_1",
      status: "pending",
      metadata: {
        payload: {
          request_id: "req_1",
        },
      },
    });
  });

  it("drops a pending optimistic user message once the server transcript contains the same request id", () => {
    const store = createChatRuntimeStore();

    store.updateTranscriptMessages("conv_1", [
      makePendingOptimisticUserMessage("temp_1", "Hello", "req_1"),
    ]);
    store.replaceTranscript("conv_1", {
      messages: [
        {
          ...makeMessage("msg_1", "user", "Hello"),
          metadata: {
            event_type: "user_message",
            payload: {
              text: "Hello",
              request_id: "req_1",
            },
            run_id: "run_1",
            activity_item_count: 0,
            stream_checkpoint_event_id: null,
          },
        },
      ],
      hasMore: false,
      nextCursor: null,
    });

    const record = store.getConversation("conv_1");
    expect(record.transcript.messages).toHaveLength(1);
    expect(record.transcript.messages[0].id).toBe("msg_1");
  });

  it("can reset the transport replay cursor for a restarted stream segment", () => {
    const store = createChatRuntimeStore();

    store.noteTransportProgress("conv_1", {
      eventId: 42,
      atMs: 1_000,
    });
    store.noteTransportProgress("conv_1", {
      eventId: 0,
      atMs: 2_000,
      reset: true,
    });

    const record = store.getConversation("conv_1");
    expect(record.lastEventId).toBe(0);
    expect(record.updatedAtMs).toBe(2_000);
  });

  it("tracks queued follow-ups separately from the active runtime", () => {
    const store = createChatRuntimeStore();

    store.noteQueuedTurn("conv_1", {
      queuePosition: 2,
      runId: "run_2",
      userMessageId: "msg_2",
      blockedByRunId: "run_1",
      createdAt: "2026-01-01T00:00:02.000Z",
    });
    store.noteQueuedTurn("conv_1", {
      queuePosition: 1,
      runId: "run_1_next",
      userMessageId: "msg_1_next",
      blockedByRunId: "run_1",
      createdAt: "2026-01-01T00:00:01.000Z",
    });
    store.removeQueuedTurn("conv_1", "run_1_next");

    expect(store.getConversation("conv_1").queuedTurns).toEqual([
      {
        queuePosition: 2,
        runId: "run_2",
        userMessageId: "msg_2",
        blockedByRunId: "run_1",
        createdAt: "2026-01-01T00:00:02.000Z",
      },
    ]);
  });

  it("preserves local queued follow-up text across authoritative sync", () => {
    const store = createChatRuntimeStore();

    store.noteQueuedTurn("conv_1", {
      queuePosition: 1,
      runId: "run_queued",
      userMessageId: "msg_queued",
      blockedByRunId: "run_active",
      createdAt: "2026-01-01T00:00:01.000Z",
      text: "Do not generate an image",
    });

    store.setQueuedTurns("conv_1", [
      {
        queuePosition: 1,
        runId: "run_queued",
        userMessageId: "msg_queued",
        blockedByRunId: "run_active",
        createdAt: "2026-01-01T00:00:01.000Z",
      },
    ]);

    expect(store.getConversation("conv_1").queuedTurns).toEqual([
      {
        queuePosition: 1,
        runId: "run_queued",
        userMessageId: "msg_queued",
        blockedByRunId: "run_active",
        createdAt: "2026-01-01T00:00:01.000Z",
        text: "Do not generate an image",
      },
    ]);
  });
});
