import { describe, expect, it } from "vitest";

import {
  createInitialStreamRuntimeState,
  streamRuntimeReducer,
} from "./reducer";
import type { RunActivityItem } from "./types";

function makeToolActivity(overrides?: Partial<RunActivityItem>): RunActivityItem {
  return {
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
      position: 6,
    },
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("stream runtime reducer", () => {
  it("rebuilds projected content from hydrated runtime snapshots", () => {
    const next = streamRuntimeReducer(createInitialStreamRuntimeState(), {
      type: "hydrate_runtime",
      phase: "streaming",
      draftText: "Hello world",
      activityItems: [makeToolActivity()],
      liveMessage: {
        id: "assist_1",
        role: "assistant",
        content: [],
        activityItems: [],
        createdAt: new Date("2026-01-01T00:00:01.000Z"),
        metadata: {
          run_id: "run_1",
          payload: {
            text: "Hello world",
            status: "running",
          },
        },
        status: "streaming",
      },
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
    });

    expect(next.phase).toBe("streaming");
    expect(next.draftText).toBe("Hello world");
    expect(next.liveMessage?.id).toBe("assist_1");
    expect(next.content).toMatchObject([
      { type: "text", text: "Hello ", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", text: "world", phase: "final" },
    ]);
  });

  it("reprojects the live message when activity items change locally", () => {
    const seeded = streamRuntimeReducer(createInitialStreamRuntimeState(), {
      type: "hydrate_runtime",
      phase: "streaming",
      draftText: "Hello world",
      activityItems: [makeToolActivity()],
      liveMessage: {
        id: "assist_1",
        role: "assistant",
        content: [],
        activityItems: [],
        createdAt: new Date("2026-01-01T00:00:01.000Z"),
        metadata: {
          run_id: "run_1",
          payload: {
            text: "Hello world",
            status: "running",
          },
        },
        status: "streaming",
      },
    });

    const next = streamRuntimeReducer(seeded, {
      type: "set_activity_items",
      activityItems: [
        makeToolActivity(),
        makeToolActivity({
          id: "activity_2",
          itemKey: "tool:call_2",
          sequence: 2,
          payload: {
            tool_call_id: "call_2",
            tool_name: "retrieval_project_files",
            position: 12,
            result: { status: "completed" },
          },
        }),
      ],
    });

    expect(next.liveMessage?.activityItems).toHaveLength(2);
    expect(next.content).toMatchObject([
      { type: "text", text: "Hello ", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", text: "world", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_2", phase: "worklog" },
    ]);
  });

  it("prefers hydrated draft text over stale checkpoint live-message text", () => {
    const next = streamRuntimeReducer(createInitialStreamRuntimeState(), {
      type: "hydrate_runtime",
      phase: "streaming",
      draftText: "Fresh runtime text after refresh",
      activityItems: [
        makeToolActivity({
          payload: {
            tool_call_id: "call_1",
            tool_name: "retrieval_web_search",
            position: 18,
          },
        }),
      ],
      liveMessage: {
        id: "assist_1",
        role: "assistant",
        content: [],
        activityItems: [],
        createdAt: new Date("2026-01-01T00:00:01.000Z"),
        metadata: {
          run_id: "run_1",
          payload: {
            text: "Stale checkpoint",
            status: "running",
          },
        },
        status: "streaming",
      },
      runId: "run_1",
      runMessageId: "msg_1",
      assistantMessageId: "assist_1",
    });

    expect(next.draftText).toBe("Fresh runtime text after refresh");
    expect(next.liveMessage?.metadata?.payload).toMatchObject({
      text: "Fresh runtime text after refresh",
    });
    expect(next.content).toMatchObject([
      { type: "text", text: "Fresh runtime text", phase: "worklog" },
      { type: "tool-call", toolCallId: "call_1", phase: "worklog" },
      { type: "text", text: " after refresh", phase: "final" },
    ]);
  });
});
