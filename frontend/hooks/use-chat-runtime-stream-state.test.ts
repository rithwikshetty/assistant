import { describe, expect, it, vi } from "vitest";
import {
  hydratePausedState,
  resolveReconnectSnapshot,
} from "./use-chat-runtime-stream-state";
import { createInitialStreamRuntimeState } from "@/lib/chat/runtime/reducer";

describe("use-chat-runtime-stream state helpers", () => {
  it("resolves reconnect snapshot from explicit runtime seed", () => {
    const snapshot = resolveReconnectSnapshot({
      conversationId: "conv_1",
      runId: "run_1",
      runMessageId: "msg_1",
      draftText: "Working",
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
      currentStatusLabel: "Thinking",
      options: {
        assistantMessageId: "assist_1",
        resumeSinceStreamEventId: 42,
      },
    });

    expect(snapshot).toEqual({
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
      sinceStreamEventId: 42,
      draftText: "Working",
      activityItems: [
        expect.objectContaining({
          itemKey: "tool:call_1",
        }),
      ],
      statusLabel: "Thinking",
    });
  });

  it("hydrates paused runtime and input gate from runtime snapshot data", async () => {
    const dispatch = vi.fn();
    const setInputGate = vi.fn();
    const markLocalPause = vi.fn();

    await hydratePausedState({
      conversationId: "conv_1",
      options: {
        runId: "run_1",
        runMessageId: "msg_1",
        assistantMessageId: "assist_1",
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
        draftText: "Need input",
        activityItems: [],
      },
      dispatch,
      setInputGate,
      markLocalPause,
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: "hydrate_runtime",
      phase: "paused_for_input",
      statusLabel: "Waiting for your input",
      draftText: "Need input",
      activityItems: [],
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
    });
    expect(setInputGate).toHaveBeenCalledWith({
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_1",
        runId: "run_1",
        messageId: "assist_1",
        requests: [
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
      },
    });
    expect(markLocalPause).toHaveBeenCalledWith("conv_1");
  });

  it("falls back to runMessageId when paused state has no assistant message id", async () => {
    const dispatch = vi.fn();
    const setInputGate = vi.fn();
    const markLocalPause = vi.fn();

    await hydratePausedState({
      conversationId: "conv_2",
      options: {
        runId: "run_2",
        runMessageId: "msg_2",
        assistantMessageId: null,
        pendingRequests: [
          {
            callId: "call_2",
            toolName: "request_user_input",
            request: {
              tool: "request_user_input",
              title: "Confirm",
              prompt: "Pick one option.",
              questions: [
                {
                  id: "confirm",
                  question: "Proceed?",
                  options: [
                    { label: "Yes", description: "Continue." },
                    { label: "No", description: "Stop." },
                  ],
                },
              ],
            },
            result: {
              status: "pending",
              interaction_type: "user_input",
              request: {
                tool: "request_user_input",
                title: "Confirm",
                prompt: "Pick one option.",
                questions: [
                  {
                    id: "confirm",
                    question: "Proceed?",
                    options: [
                      { label: "Yes", description: "Continue." },
                      { label: "No", description: "Stop." },
                    ],
                  },
                ],
              },
            },
          },
        ],
      },
      dispatch,
      setInputGate,
      markLocalPause,
    });

    expect(setInputGate).toHaveBeenCalledWith({
      isPausedForInput: true,
      pausedPayload: {
        conversationId: "conv_2",
        runId: "run_2",
        messageId: "msg_2",
        requests: expect.any(Array),
      },
    });
  });

  it("keeps runtime defaults empty when there is no reconnect seed", () => {
    const state = createInitialStreamRuntimeState();
    const snapshot = resolveReconnectSnapshot({
      conversationId: "conv_2",
      runId: state.runId,
      runMessageId: state.runMessageId,
      draftText: state.draftText,
      activityItems: state.activityItems,
      currentStatusLabel: state.statusLabel,
    });

    expect(snapshot.sinceStreamEventId).toBe(0);
    expect(snapshot.draftText).toBe("");
    expect(snapshot.activityItems).toEqual([]);
    expect(snapshot.statusLabel).toBe("Starting");
  });
});
