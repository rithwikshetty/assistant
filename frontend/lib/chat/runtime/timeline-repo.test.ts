import { describe, expect, it } from "vitest";
import type { TimelineItem } from "@/lib/api/chat";
import { mapTimelineItem } from "./timeline-repo";

describe("timeline-repo", () => {
  it("ignores standalone tool_result events in timeline projection", () => {
    const toolResult = {
      id: "evt_tool_result",
      seq: 10,
      run_id: "run_1",
      type: "tool_result",
      actor: "tool",
      created_at: "2026-02-27T01:35:35.362403Z",
      role: null,
      payload: {
        tool_name: "request_user_input",
        tool_call_id: "call_123",
        result: { status: "completed" },
      },
    } as unknown as TimelineItem;

    expect(mapTimelineItem(toolResult)).toBeNull();
  });

  it("keeps assistant timeline events as renderable messages", () => {
    const assistantFinal: TimelineItem = {
      id: "evt_assistant",
      seq: 6,
      run_id: "run_1",
      type: "assistant_message_final",
      actor: "assistant",
      created_at: "2026-02-27T01:35:16.577601Z",
      role: "assistant",
      text: "Final answer",
      activity_items: [
        {
          id: "activity_1",
          run_id: "run_1",
          item_key: "user_input:call_123",
          kind: "user_input",
          status: "completed",
          title: "Gathering Input",
          summary: "Pick a scope",
          sequence: 6,
          payload: {
            tool_call_id: "call_123",
            tool_name: "request_user_input",
            request: {
              tool: "request_user_input",
              title: "Scope",
              prompt: "Choose an approach",
              questions: [{
                id: "q1",
                question: "Which approach?",
                options: [
                  { label: "Lean", description: "Give a quick answer" },
                  { label: "Detailed", description: "Give a fuller answer" },
                ],
              }],
            },
            result: {
              status: "completed",
              interaction_type: "user_input",
              request: {
                tool: "request_user_input",
                title: "Scope",
                prompt: "Choose an approach",
                questions: [{
                  id: "q1",
                  question: "Which approach?",
                  options: [
                    { label: "Lean", description: "Give a quick answer" },
                    { label: "Detailed", description: "Give a fuller answer" },
                  ],
                }],
              },
              answers: [{ question_id: "q1", option_label: "Detailed" }],
            },
          },
          created_at: "2026-02-27T01:35:16.577601Z",
          updated_at: "2026-02-27T01:35:17.577601Z",
        },
      ],
      payload: { status: "completed" },
    };

    const mapped = mapTimelineItem(assistantFinal);

    expect(mapped?.role).toBe("assistant");
    expect(mapped?.content).toHaveLength(2);
    expect(mapped?.activityItems).toHaveLength(1);
  });

  it("maps persisted response latency and finish reason metadata", () => {
    const assistantFinal: TimelineItem = {
      id: "evt_assistant_latency",
      seq: 8,
      run_id: "run_1",
      type: "assistant_message_final",
      actor: "assistant",
      created_at: "2026-02-27T01:36:16.577601Z",
      role: "assistant",
      text: "Done",
      payload: {
        status: "cancelled",
        response_latency_ms: 12_345,
        finish_reason: "cancelled",
      },
    };

    const mapped = mapTimelineItem(assistantFinal);
    expect(mapped?.responseLatencyMs).toBe(12_345);
    expect(mapped?.finishReason).toBe("cancelled");
  });

  it("projects partial assistant rows with live stream ordering", () => {
    const assistantPartial: TimelineItem = {
      id: "evt_assistant_partial",
      seq: 7,
      run_id: "run_1",
      type: "assistant_message_partial",
      actor: "assistant",
      created_at: "2026-02-27T01:35:46.577601Z",
      role: "assistant",
      text: "Preamble before tool. Final tail",
      activity_items: [
        {
          id: "activity_1",
          run_id: "run_1",
          item_key: "tool:call_1",
          kind: "tool",
          status: "completed",
          title: "Web Search",
          summary: "example query",
          sequence: 1,
          payload: {
            tool_call_id: "call_1",
            tool_name: "retrieval_web_search",
            position: 24,
            result: { content: "Found sources", citations: [] },
          },
          created_at: "2026-02-27T01:35:46.577601Z",
          updated_at: "2026-02-27T01:35:47.577601Z",
        },
      ],
      payload: { status: "running" },
    };

    const mapped = mapTimelineItem(assistantPartial);

    expect(mapped?.status).toBe("streaming");
    expect(mapped?.content).toMatchObject([
      { type: "text", text: "Preamble before tool. Final", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", text: " tail", phase: "final" },
    ]);
  });

  it("maps user attachment metadata from the canonical timeline payload", () => {
    const userMessage: TimelineItem = {
      id: "evt_user_attachment",
      seq: 9,
      run_id: null,
      type: "user_message",
      actor: "user",
      created_at: "2026-02-27T01:37:16.577601Z",
      role: "user",
      text: "Please review",
      payload: {
        text: "Please review",
        attachments: [
          {
            id: "file_1",
            original_filename: "scope.pdf",
            file_type: "application/pdf",
            file_size: 1024,
          },
        ],
      },
    };

    const mapped = mapTimelineItem(userMessage);
    expect(mapped?.attachments).toEqual([
      {
        id: "file_1",
        name: "scope.pdf",
        contentType: "application/pdf",
        fileSize: 1024,
      },
    ]);
  });
});
