import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationSummary } from "@/lib/api/auth";
import { createInitialStreamRuntimeState } from "@/lib/chat/runtime/reducer";
import type { Message } from "@/lib/chat/runtime/types";
import { queryKeys } from "@/lib/query/query-keys";

const { createRunMock } = vi.hoisted(() => ({
  createRunMock: vi.fn(),
}));

vi.mock("@/lib/api/chat", () => ({
  cancelRun: vi.fn(),
  createRun: createRunMock,
}));

import { sendMessageAction } from "./use-chat-runtime-stream-actions";

function buildConversationSummary(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    id: "conv_1",
    title: "New Chat",
    updated_at: "2026-03-11T00:00:00Z",
    last_message_at: "2026-03-11T00:00:00Z",
    message_count: 1,
    last_message_preview: "Original preview",
    project_id: null,
    parent_conversation_id: null,
    archived: false,
    archived_at: null,
    archived_by: null,
    owner_id: "user_1",
    owner_name: "Test User",
    owner_email: "test@example.com",
    is_owner: true,
    can_edit: true,
    awaiting_user_input: true,
    ...overrides,
  };
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });
  return { promise, resolve, reject };
}

function applyMessageUpdater(
  current: Message[],
  updater: Message[] | ((prev: Message[]) => Message[]),
): Message[] {
  return typeof updater === "function" ? updater(current) : updater;
}

describe("sendMessageAction", () => {
  beforeEach(() => {
    createRunMock.mockReset();
  });

  it("rolls back optimistic sidebar state when createRun fails", async () => {
    const queryClient = new QueryClient();
    const originalSummary = buildConversationSummary();
    queryClient.setQueryData(queryKeys.conversations.list("user_1"), [originalSummary]);
    createRunMock.mockRejectedValueOnce(new Error("backend unavailable"));

    let messages: Message[] = [];
    const clearActiveRuntime = vi.fn();

    await sendMessageAction({
      conversationId: "conv_1",
      content: "Draft message",
      inputGateRef: { current: { isPausedForInput: false, pausedPayload: null } },
      streamRef: { current: createInitialStreamRuntimeState() },
      streamAbortControllerRef: { current: null },
      createRunAbortControllerRef: { current: null },
      getActiveRunId: () => null,
      setError: vi.fn(),
      setMessages: (updater) => {
        messages = applyMessageUpdater(messages, updater);
      },
      setInputGate: vi.fn(),
      dispatch: vi.fn(),
      markLocalStart: vi.fn(),
      clearActiveRuntime,
      connectToStream: vi.fn(),
      queryClient,
    });

    expect(clearActiveRuntime).toHaveBeenCalledTimes(1);
    expect(messages).toEqual([]);
    expect(
      queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations.list("user_1")),
    ).toEqual([originalSummary]);
  });

  it("does not overwrite newer cache state when rollback runs after another update", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.conversations.list("user_1"), [buildConversationSummary()]);
    const deferred = createDeferred<{ run_id: string; user_message_id: string; status: string }>();
    createRunMock.mockReturnValueOnce(deferred.promise);

    let messages: Message[] = [];
    const actionPromise = sendMessageAction({
      conversationId: "conv_1",
      content: "Draft message",
      inputGateRef: { current: { isPausedForInput: false, pausedPayload: null } },
      streamRef: { current: createInitialStreamRuntimeState() },
      streamAbortControllerRef: { current: null },
      createRunAbortControllerRef: { current: null },
      getActiveRunId: () => null,
      setError: vi.fn(),
      setMessages: (updater) => {
        messages = applyMessageUpdater(messages, updater);
      },
      setInputGate: vi.fn(),
      dispatch: vi.fn(),
      markLocalStart: vi.fn(),
      clearActiveRuntime: vi.fn(),
      connectToStream: vi.fn(),
      queryClient,
    });

    queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations.list("user_1"), [
      buildConversationSummary({
        updated_at: "2026-03-12T10:00:00Z",
        last_message_at: "2026-03-12T10:00:00Z",
        message_count: 9,
        last_message_preview: "Server-correct preview",
        awaiting_user_input: false,
      }),
    ]);

    deferred.reject(new Error("backend unavailable"));
    await actionPromise;

    expect(messages).toEqual([]);
    expect(
      queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations.list("user_1")),
    ).toEqual([
      expect.objectContaining({
        updated_at: "2026-03-12T10:00:00Z",
        last_message_at: "2026-03-12T10:00:00Z",
        message_count: 9,
        last_message_preview: "Server-correct preview",
        awaiting_user_input: false,
      }),
    ]);
  });

  it("queues follow-ups without appending them to the transcript immediately", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.conversations.list("user_1"), [buildConversationSummary()]);
    createRunMock.mockResolvedValueOnce({
      run_id: "run_queued",
      user_message_id: "msg_queued",
      status: "queued",
      queue_position: 1,
    });

    let messages: Message[] = [];
    const noteQueuedTurn = vi.fn();

    const activeStream = createInitialStreamRuntimeState();
    activeStream.phase = "streaming";
    activeStream.runId = "run_active";

    await sendMessageAction({
      conversationId: "conv_1",
      content: "Queued follow-up",
      inputGateRef: { current: { isPausedForInput: false, pausedPayload: null } },
      streamRef: { current: activeStream },
      streamAbortControllerRef: { current: null },
      createRunAbortControllerRef: { current: null },
      getActiveRunId: () => "run_active",
      setError: vi.fn(),
      setMessages: (updater) => {
        messages = applyMessageUpdater(messages, updater);
      },
      setInputGate: vi.fn(),
      dispatch: vi.fn(),
      markLocalStart: vi.fn(),
      noteQueuedTurn,
      clearActiveRuntime: vi.fn(),
      connectToStream: vi.fn(),
      queryClient,
    });

    expect(messages).toEqual([]);
    expect(noteQueuedTurn).toHaveBeenCalledWith(
      "conv_1",
      expect.objectContaining({
        runId: "run_queued",
        userMessageId: "msg_queued",
        blockedByRunId: "run_active",
        text: "Queued follow-up",
      }),
    );
  });
});
