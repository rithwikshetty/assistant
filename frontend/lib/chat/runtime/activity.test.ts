import { describe, expect, it } from "vitest";

import {
  applyOptimisticToolResultToActivityItems,
  projectSettledMessageContent,
  projectStreamContent,
} from "./activity";
import type { RunActivityItem } from "./types";

function makeToolActivity(overrides?: Partial<RunActivityItem>): RunActivityItem {
  return {
    id: "activity_1",
    runId: "run_1",
    itemKey: "tool:call_1",
    kind: "tool",
    status: "running",
    title: "web search",
    summary: "uk qs market update",
    sequence: 2,
    payload: {
      tool_call_id: "call_1",
      tool_name: "retrieval_web_search",
      position: 34,
    },
    createdAt: "2026-03-10T00:00:00Z",
    updatedAt: "2026-03-10T00:00:01Z",
    ...overrides,
  };
}

describe("activity projector", () => {
  it("keeps completed text and tool activity interleaved by stored positions", () => {
    const activityItems: RunActivityItem[] = [
      makeToolActivity({
        id: "activity_1",
        itemKey: "tool:call_1",
        sequence: 2,
        payload: {
          tool_call_id: "call_1",
          tool_name: "retrieval_web_search",
          position: 34,
          result: { content: "Found two sources", citations: [] },
        },
      }),
      makeToolActivity({
        id: "activity_2",
        itemKey: "tool:call_2",
        title: "Knowledge search",
        sequence: 4,
        payload: {
          tool_call_id: "call_2",
          tool_name: "retrieval_project_files",
          position: 83,
          result: { content: "Found six references", sources: [] },
        },
      }),
    ];

    const content = projectSettledMessageContent({
      text:
        "I'll pull together a short QS-focused update. I'll tailor this as a UK-focused note. Final answer here.",
      activityItems,
    });

    expect(content).toMatchObject([
      { type: "text", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_2", phase: "worklog" },
      { type: "text", phase: "final" },
    ]);
    expect(content[0].type === "text" ? content[0].text : "").toContain("I'll pull together");
    expect(content[2].type === "text" ? content[2].text : "").toContain("I'll tailor this");
    expect(content[4].type === "text" ? content[4].text : "").toContain("Final answer here.");
  });

  it("prefers user_input review items over duplicate interactive tool rows", () => {
    const activityItems: RunActivityItem[] = [
      {
        id: "tool_1",
        runId: "run_1",
        itemKey: "tool:call_1",
        kind: "tool",
        status: "completed",
        title: "Gathering Input",
        summary: "Scope",
        sequence: 1,
        payload: {
          tool_call_id: "call_1",
          tool_name: "request_user_input",
          result: { status: "completed" },
        },
        createdAt: "2026-03-10T00:00:00Z",
        updatedAt: "2026-03-10T00:00:01Z",
      },
      {
        id: "user_input_1",
        runId: "run_1",
        itemKey: "user_input:call_1",
        kind: "user_input",
        status: "completed",
        title: "Gathering Input",
        summary: "Scope",
        sequence: 2,
        payload: {
          tool_call_id: "call_1",
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
        createdAt: "2026-03-10T00:00:00Z",
        updatedAt: "2026-03-10T00:00:01Z",
      },
    ];

    const content = projectSettledMessageContent({
      text: "Done",
      activityItems,
    });

    expect(content).toHaveLength(2);
    expect(content[0]).toMatchObject({
      type: "tool-call",
      toolName: "request_user_input",
      toolCallId: "call_1",
      phase: "worklog",
    });
    expect(content[1]).toMatchObject({
      type: "text",
      text: "Done",
      phase: "final",
    });
  });

  it("updates an existing tool row optimistically without rebuilding from transport deltas", () => {
    const activityItems: RunActivityItem[] = [
      makeToolActivity({
        payload: {
          tool_call_id: "call_1",
          tool_name: "retrieval_web_search",
          position: 24,
          result: { content: "Searching", citations: [] },
        },
      }),
    ];

    const nextItems = applyOptimisticToolResultToActivityItems({
      activityItems,
      toolCallId: "call_1",
      result: { status: "completed", count: 2 },
    });

    expect(nextItems).toHaveLength(1);
    expect(nextItems?.[0]).toMatchObject({
      status: "completed",
      payload: {
        tool_call_id: "call_1",
        result: { status: "completed", count: 2 },
      },
    });

    const content = projectStreamContent({
      draftText: "Preamble before tool. Final tail",
      activityItems: nextItems ?? [],
    });

    expect(content).toMatchObject([
      { type: "text", text: "Preamble before tool. Final", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", text: " tail", phase: "final" },
    ]);
  });
});
