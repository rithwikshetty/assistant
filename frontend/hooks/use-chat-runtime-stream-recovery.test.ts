import { describe, expect, it } from "vitest";

import type { ConversationRuntimeResponse } from "@/lib/api/chat";
import { resolveAuthoritativeSnapshotFromRuntime } from "./use-chat-runtime-stream-recovery";

function makeRuntime(overrides?: Partial<ConversationRuntimeResponse>): ConversationRuntimeResponse {
  return {
    conversation_id: "conv_1",
    active: true,
    status: "running",
    run_id: "run_1",
    run_message_id: "msg_1",
    assistant_message_id: "assist_1",
    status_label: "Thinking",
    draft_text: "Working",
    last_seq: 12,
    resume_since_stream_event_id: 12,
    activity_cursor: 12,
    usage: {},
    pending_requests: [],
    activity_items: [
      {
        id: "activity_1",
        run_id: "run_1",
        item_key: "tool:call_1",
        kind: "tool",
        status: "running",
        title: "web search",
        summary: null,
        sequence: 1,
        payload: {
          tool_call_id: "call_1",
          tool_name: "retrieval_web_search",
        },
        created_at: "2026-01-01T00:00:00.000Z",
        updated_at: "2026-01-01T00:00:00.000Z",
      },
    ],
    ...overrides,
  };
}

describe("use-chat-runtime-stream recovery helpers", () => {
  it("normalizes authoritative runtime without session fallbacks", () => {
    const snapshot = resolveAuthoritativeSnapshotFromRuntime(
      makeRuntime({
        run_message_id: null,
        pending_requests: [
          {
            call_id: "call_1",
            tool_name: "request_user_input",
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
        live_message: {
          id: "assist_1",
          seq: 13,
          run_id: "run_1",
          type: "assistant_message_partial",
          actor: "assistant",
          created_at: "2026-01-01T00:00:01.000Z",
          role: "assistant",
          text: "Working",
          activity_items: [],
          payload: {
            text: "Working",
            status: "running",
          },
        },
      }),
    );

    expect(snapshot).toEqual({
      status: "running",
      runId: "run_1",
      runMessageId: null,
      currentStep: "Thinking",
      assistantMessageId: "assist_1",
      resumeSinceStreamEventId: 12,
      activityCursor: 12,
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
      queuedTurns: [],
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
          payload: {
            tool_call_id: "call_1",
            tool_name: "retrieval_web_search",
          },
          createdAt: "2026-01-01T00:00:00.000Z",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      ],
      liveMessage: {
        id: "assist_1",
        role: "assistant",
        content: [{ type: "text", text: "Working", phase: "final" }],
        activityItems: [],
        createdAt: new Date("2026-01-01T00:00:01.000Z"),
        metadata: {
          event_type: "assistant_message_partial",
          payload: {
            text: "Working",
            status: "running",
          },
          run_id: "run_1",
          activity_item_count: 0,
          stream_checkpoint_event_id: null,
        },
        status: "streaming",
        attachments: undefined,
        responseLatencyMs: null,
        finishReason: null,
        userFeedbackId: null,
        userFeedbackRating: null,
        userFeedbackUpdatedAt: null,
        suggestedQuestions: null,
      },
    });
  });
});
