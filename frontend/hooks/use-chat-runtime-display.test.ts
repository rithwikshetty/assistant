import { describe, expect, it } from "vitest";

import type { Message, StreamRenderSlice } from "@/lib/chat/runtime/types";
import { resolveStreamDisplayState, resolveStreamPresence } from "./use-chat-runtime-display";

function makeStream(overrides?: Partial<StreamRenderSlice>): StreamRenderSlice {
  return {
    phase: "streaming",
    statusLabel: "Thinking",
    draftText: "Working",
    activityItems: [],
    liveMessage: null,
    runId: "run_1",
    runMessageId: "msg_1",
    assistantMessageId: "assist_1",
    content: [{ type: "text", text: "Working" }],
    ...overrides,
  };
}

function makeAssistantMessage(overrides?: Partial<Message>): Message {
  return {
    id: "assist_1",
    role: "assistant",
    content: [{ type: "text", text: "Final answer" }],
    createdAt: new Date("2026-01-01T00:00:00.000Z"),
    status: "completed",
    metadata: {
      run_id: "run_1",
    },
    ...overrides,
  };
}

describe("use-chat-runtime display helpers", () => {
  it("shows the streaming shell while a run is starting even without rendered content", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "starting",
        draftText: "",
        content: [],
        statusLabel: "Starting",
      }),
      messages: [],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(true);
    expect(display.status.label).toBe("Starting");
  });

  it("drops the sticky starting label once stream content is already visible", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "streaming",
        statusLabel: "Starting",
        content: [{ type: "text", text: "Let me work through that." }],
      }),
      messages: [],
      isPausedForInput: false,
    });

    expect(display.status.phase).toBe("responding");
    expect(display.status.label).toBe("Writing response");
  });

  it("promotes a starting run into thinking once the backend reports hidden model work", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "starting",
        draftText: "",
        content: [],
        statusLabel: "Thinking",
      }),
      messages: [],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(true);
    expect(display.status.phase).toBe("model");
    expect(display.status.label).toBe("Thinking");
  });

  it("keeps an explicit model status over visible text while the model is still working", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "streaming",
        statusLabel: "Considering project details",
        content: [{ type: "text", text: "I found strong matches already." }],
      }),
      messages: [],
      isPausedForInput: false,
    });

    expect(display.status.phase).toBe("model");
    expect(display.status.label).toBe("Considering project details");
  });

  it("prefers the active tool label over starting once tool work is visible", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "streaming",
        statusLabel: "Starting",
        draftText: "",
        content: [{ type: "tool-call", toolCallId: "call_1", toolName: "retrieval_web_search" }],
      }),
      messages: [],
      isPausedForInput: false,
    });

    expect(display.status.phase).toBe("tool");
    expect(display.status.label).toBe("Using Web Search");
  });

  it("suppresses the completing shell once the final assistant for the same run is present", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "completing",
        content: [{ type: "text", text: "Stale bubble" }],
      }),
      messages: [makeAssistantMessage()],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(false);
  });

  it("suppresses a stale live shell even if the local phase still says streaming", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "streaming",
        content: [{ type: "text", text: "Stale live work" }],
      }),
      messages: [makeAssistantMessage()],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(false);
  });

  it("suppresses active-stream presence once a terminal assistant exists for the same run", () => {
    const isStreaming = resolveStreamPresence({
      stream: {
        phase: "streaming",
        runId: "run_1",
        runMessageId: "msg_1",
        assistantMessageId: "assist_1",
      },
      messages: [makeAssistantMessage()],
      isPausedForInput: false,
    });

    expect(isStreaming).toBe(false);
  });

  it("keeps paused-for-input visible when waiting on the user", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "paused_for_input",
        statusLabel: "Waiting for your input",
        draftText: "",
        content: [],
      }),
      messages: [],
      isPausedForInput: true,
    });

    expect(display.isStreaming).toBe(true);
    expect(display.status.label).toBe("Waiting for your input");
  });

  it("keeps the shell visible during completion if the only final assistant belongs to another run", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "completing",
        content: [{ type: "text", text: "Still finishing current run" }],
      }),
      messages: [
        makeAssistantMessage({
          id: "assist_old",
          metadata: { run_id: "run_old" },
        }),
      ],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(true);
  });

  it("keeps the starting shell visible when assistantMessageId belongs to an older run", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "starting",
        runId: "run_queued",
        runMessageId: "msg_queued",
        assistantMessageId: "assist_old",
        statusLabel: "Starting",
        draftText: "",
        content: [],
      }),
      messages: [
        makeAssistantMessage({
          id: "assist_old",
          metadata: { run_id: "run_active" },
        }),
      ],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(true);
    expect(display.status.label).toBe("Starting");
  });

  it("keeps streamed content visible when the run ends in an error after output already exists", () => {
    const display = resolveStreamDisplayState({
      stream: makeStream({
        phase: "error",
        statusLabel: "Generation failed",
        draftText: "Partial answer that should stay visible",
        content: [{ type: "text", text: "Partial answer that should stay visible" }],
      }),
      messages: [],
      isPausedForInput: false,
    });

    expect(display.isStreaming).toBe(true);
    expect(display.status.label).toBe("Generation failed");
  });
});
