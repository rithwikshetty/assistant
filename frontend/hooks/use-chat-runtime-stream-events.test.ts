import { describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "@/lib/api/chat";
import { createInitialStreamRuntimeState } from "@/lib/chat/runtime/reducer";
import { createStreamEventHandler } from "./use-chat-runtime-stream-events";

function makeEventHandlerHarness(overrides?: {
  recoverRuntimeState?: (options?: {
    allowAuthoritativeCheck?: boolean;
    refetchOnIdle?: boolean;
    markCompleteOnIdle?: boolean;
  }) => Promise<"running" | "paused" | "idle">;
  allowNoActiveRecheck?: boolean;
  onNoActiveDuringRecheck?: () => void;
  streamState?: Partial<ReturnType<typeof createInitialStreamRuntimeState>>;
}) {
  const controller = new AbortController();
  const mountedRef = { current: true };
  const streamRef = {
    current: {
      ...createInitialStreamRuntimeState(),
      phase: "streaming" as const,
      statusLabel: "Thinking",
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_streaming",
      draftText: "Working",
      ...overrides?.streamState,
    },
  };

  const dispatch = vi.fn();
  const requestAuthoritativeSync = vi.fn();
  const setInputGate = vi.fn();
  const refetchMessages = vi.fn(async () => undefined);
  const markLocalPause = vi.fn();
  const markLocalComplete = vi.fn();
  const clearStreamError = vi.fn();
  const reportStreamError = vi.fn();
  const onNoActiveDuringRecheck = vi.fn(() => {
    overrides?.onNoActiveDuringRecheck?.();
  });
  const recoverRuntimeState = vi.fn(
    overrides?.recoverRuntimeState ??
    (async () => "idle" as const),
  );

  const onEvent = createStreamEventHandler({
    conversationId: "conv_1",
    allowNoActiveRecheck: overrides?.allowNoActiveRecheck,
    onNoActiveDuringRecheck,
    controller,
    mountedRef,
    streamRef,
    requestAuthoritativeSync,
    dispatch,
    setInputGate,
    refetchMessagesRef: { current: refetchMessages },
    markLocalPause,
    markLocalComplete,
    clearStreamError,
    reportStreamError,
    recoverRuntimeState,
  });

  return {
    onEvent,
    dispatch,
    requestAuthoritativeSync,
    setInputGate,
    refetchMessages,
    markLocalPause,
    markLocalComplete,
    clearStreamError,
    reportStreamError,
    recoverRuntimeState,
    onNoActiveDuringRecheck,
  };
}

describe("use-chat-runtime-stream-events", () => {
  it("treats runtime_update as an authoritative sync trigger", async () => {
    const harness = makeEventHandlerHarness();

    const runtimeUpdateEvent: StreamEvent = {
      id: 10,
      type: "runtime_update",
      data: { statusLabel: "Generating response" },
    };

    await harness.onEvent(runtimeUpdateEvent);

    expect(harness.clearStreamError).toHaveBeenCalledTimes(1);
    expect(harness.requestAuthoritativeSync).toHaveBeenCalledTimes(1);
    expect(harness.dispatch).not.toHaveBeenCalled();
  });

  it("treats replay_gap as a hard authoritative resync", async () => {
    const harness = makeEventHandlerHarness({
      recoverRuntimeState: async () => "running",
    });

    const replayGapEvent: StreamEvent = {
      id: 9,
      type: "replay_gap",
      data: {
        expectedNextStreamEventId: 10,
        resumedAtStreamEventId: 0,
      },
    };

    await harness.onEvent(replayGapEvent);

    expect(harness.recoverRuntimeState).toHaveBeenCalledWith({
      allowAuthoritativeCheck: true,
      refetchOnIdle: true,
      markCompleteOnIdle: true,
    });
  });

  it("keeps repeated runtime updates transport-neutral", async () => {
    const harness = makeEventHandlerHarness();

    const runtimeUpdateEvent: StreamEvent = {
      id: 11,
      type: "runtime_update",
      data: { statusLabel: "Searching sources" },
    };

    await harness.onEvent(runtimeUpdateEvent);

    expect(harness.clearStreamError).toHaveBeenCalledTimes(1);
    expect(harness.requestAuthoritativeSync).toHaveBeenCalledTimes(1);
    expect(harness.dispatch).not.toHaveBeenCalled();
  });

  it("retries authoritative sync after no_active_stream leaves a fresh local start shell running", async () => {
    const harness = makeEventHandlerHarness({
      recoverRuntimeState: async () => "running",
      streamState: {
        phase: "streaming",
        statusLabel: "Starting",
        draftText: "",
        activityItems: [],
      },
    });

    const event: StreamEvent = {
      id: 1,
      type: "no_active_stream",
      data: {
        reason: "no_active_stream",
        conversationId: "conv_1",
        runMessageId: "msg_1",
      },
    };

    await harness.onEvent(event);

    expect(harness.recoverRuntimeState).toHaveBeenCalledWith({
      allowAuthoritativeCheck: true,
      refetchOnIdle: true,
      markCompleteOnIdle: true,
    });
    expect(harness.requestAuthoritativeSync).toHaveBeenCalledTimes(1);
  });

  it("treats run.status as an authoritative sync trigger", async () => {
    const harness = makeEventHandlerHarness();

    const event: StreamEvent = {
      id: 12,
      type: "run.status",
      data: { statusLabel: "Thinking" },
    };

    await harness.onEvent(event);

    expect(harness.clearStreamError).toHaveBeenCalledTimes(1);
    expect(harness.dispatch).toHaveBeenCalledWith({ type: "set_status", statusLabel: "Thinking" });
    expect(harness.requestAuthoritativeSync).toHaveBeenCalledTimes(1);
  });

  it("refetches transcript and resets runtime after a completed done event", async () => {
    const harness = makeEventHandlerHarness();

    const doneEvent: StreamEvent = {
      id: 100,
      type: "done",
      data: {
        conversationId: "conv_1",
        runId: "run_1",
        runMessageId: "msg_1",
        assistantMessageId: "assist_done",
        status: "completed",
        cancelled: false,
        pendingRequests: [],
        usage: null,
        conversationUsage: null,
        elapsedSeconds: null,
        costUsd: null,
      },
    };

    await harness.onEvent(doneEvent);

    expect(harness.clearStreamError).toHaveBeenCalledTimes(1);
    expect(harness.markLocalComplete).toHaveBeenCalledWith("conv_1");
    expect(harness.refetchMessages).toHaveBeenCalledTimes(1);
    expect(harness.dispatch).toHaveBeenCalledWith(expect.objectContaining({
      type: "set_run_context",
      assistantMessageId: "assist_done",
    }));
    expect(harness.dispatch).toHaveBeenCalledWith({ type: "set_phase", phase: "completing" });
    expect(harness.dispatch).toHaveBeenCalledWith({ type: "reset" });
  });

  it("hydrates paused input immediately when done pauses for input", async () => {
    const harness = makeEventHandlerHarness({
      recoverRuntimeState: async () => "paused",
    });

    const doneEvent: StreamEvent = {
      id: 101,
      type: "done",
      data: {
        conversationId: "conv_1",
        runId: "run_1",
        runMessageId: "msg_1",
        assistantMessageId: "assist_pause",
        status: "paused",
        cancelled: false,
        pendingRequests: [
          {
            callId: "call_1",
            toolName: "request_user_input",
            request: {
              tool: "request_user_input",
              title: "Approve scope",
              prompt: "Choose one option.",
              questions: [
                {
                  id: "scope",
                  question: "Approve?",
                  options: [
                    { label: "Yes", description: "Proceed now." },
                    { label: "No", description: "Stop and revise." },
                  ],
                },
              ],
            },
            result: {
              status: "pending",
              interaction_type: "user_input",
              request: {
                tool: "request_user_input",
                title: "Approve scope",
                prompt: "Choose one option.",
                questions: [
                  {
                    id: "scope",
                    question: "Approve?",
                    options: [
                      { label: "Yes", description: "Proceed now." },
                      { label: "No", description: "Stop and revise." },
                    ],
                  },
                ],
              },
            },
          },
        ],
        usage: null,
        conversationUsage: null,
        elapsedSeconds: null,
        costUsd: null,
      },
    };

    await harness.onEvent(doneEvent);

    expect(harness.clearStreamError).toHaveBeenCalledTimes(1);
    expect(harness.setInputGate).toHaveBeenCalledWith({
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_1",
        runId: "run_1",
        messageId: "assist_pause",
        requests: doneEvent.data.pendingRequests,
      },
    });
    expect(harness.dispatch).toHaveBeenCalledWith({
      type: "set_phase",
      phase: "paused_for_input",
      statusLabel: "Waiting for your input",
    });
    expect(harness.markLocalPause).toHaveBeenCalledWith("conv_1");
    expect(harness.requestAuthoritativeSync).toHaveBeenCalledTimes(1);
    expect(harness.recoverRuntimeState).not.toHaveBeenCalled();
  });

  it("skips nested recovery for no_active_stream during recheck reconnect", async () => {
    const harness = makeEventHandlerHarness({
      allowNoActiveRecheck: false,
      recoverRuntimeState: async () => "running",
    });

    const noActiveEvent: StreamEvent = {
      id: 102,
      type: "no_active_stream",
      data: { reason: "stream_closed", conversationId: null, runMessageId: null },
    };

    await harness.onEvent(noActiveEvent);

    expect(harness.onNoActiveDuringRecheck).toHaveBeenCalledTimes(1);
    expect(harness.recoverRuntimeState).not.toHaveBeenCalled();
  });

  it("recovers on recoverable error codes before surfacing a failure", async () => {
    const harness = makeEventHandlerHarness({
      recoverRuntimeState: async () => "running",
    });

    const errorEvent: StreamEvent = {
      id: 103,
      type: "error",
      data: {
        message: "connection dropped",
        code: "connection_lost",
      },
    };

    await harness.onEvent(errorEvent);

    expect(harness.recoverRuntimeState).toHaveBeenCalledWith({
      allowAuthoritativeCheck: true,
      refetchOnIdle: true,
      markCompleteOnIdle: true,
    });
    expect(harness.reportStreamError).not.toHaveBeenCalled();
  });

  it("treats WS_RELAY as recoverable and rechecks authoritatively", async () => {
    const harness = makeEventHandlerHarness({
      recoverRuntimeState: async () => "idle",
    });

    const errorEvent: StreamEvent = {
      id: 104,
      type: "error",
      data: {
        message: "WebSocket stream relay failed",
        code: "WS_RELAY",
      },
    };

    await harness.onEvent(errorEvent);

    expect(harness.recoverRuntimeState).toHaveBeenCalledWith({
      allowAuthoritativeCheck: true,
      refetchOnIdle: true,
      markCompleteOnIdle: true,
    });
    expect(harness.reportStreamError).not.toHaveBeenCalled();
    expect(harness.markLocalComplete).not.toHaveBeenCalled();
    expect(harness.refetchMessages).not.toHaveBeenCalled();
  });

  it("schedules an authoritative sync instead of nested recovery during recheck relay errors", async () => {
    const harness = makeEventHandlerHarness({
      allowNoActiveRecheck: false,
      recoverRuntimeState: async () => "running",
    });

    const errorEvent: StreamEvent = {
      id: 105,
      type: "error",
      data: {
        message: "WebSocket stream relay failed",
        code: "WS_RELAY",
      },
    };

    await harness.onEvent(errorEvent);

    expect(harness.requestAuthoritativeSync).toHaveBeenCalledTimes(1);
    expect(harness.recoverRuntimeState).not.toHaveBeenCalled();
    expect(harness.reportStreamError).not.toHaveBeenCalled();
  });

  it("preserves tool ordering metadata from live transport events", async () => {
    const harness = makeEventHandlerHarness();

    const toolStartedEvent: StreamEvent = {
      id: 106,
      type: "tool.started",
      data: {
        toolCallId: "call_1",
        toolName: "retrieval_web_search",
        arguments: { query: "car park ventilation benchmark" },
        statusLabel: "Using web search",
        position: 48,
        sequence: 2,
      },
    };

    await harness.onEvent(toolStartedEvent);

    expect(harness.dispatch).toHaveBeenCalledWith({
      type: "set_activity_items",
      activityItems: [
        expect.objectContaining({
          itemKey: "call_1",
          sequence: 2,
          payload: expect.objectContaining({
            tool_call_id: "call_1",
            tool_name: "retrieval_web_search",
            position: 48,
            sequence: 2,
          }),
        }),
      ],
    });
  });

  it("retains tool identifiers when progress arrives before a parsed start event", async () => {
    const harness = makeEventHandlerHarness();

    const progressEvent: StreamEvent = {
      id: 107,
      type: "tool.progress",
      data: {
        toolCallId: "call_2",
        toolName: "execute_code",
        query: "Running cost benchmark analysis",
        statusLabel: "Running code",
        position: 64,
        sequence: 3,
      },
    };

    await harness.onEvent(progressEvent);

    expect(harness.dispatch).toHaveBeenCalledWith({
      type: "set_activity_items",
      activityItems: [
        expect.objectContaining({
          itemKey: "call_2",
          payload: expect.objectContaining({
            tool_call_id: "call_2",
            tool_name: "execute_code",
            query: "Running cost benchmark analysis",
          }),
        }),
      ],
    });
  });
});
