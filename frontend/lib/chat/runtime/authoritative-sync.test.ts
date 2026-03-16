import { describe, expect, it } from "vitest";

import type { AuthoritativeStreamSnapshot, StreamRenderSlice } from "@/lib/chat/runtime/types";
import {
  shouldHydratePausedSnapshot,
  shouldHydrateRunningSnapshot,
} from "./authoritative-sync";

function makeStream(overrides?: Partial<StreamRenderSlice>): StreamRenderSlice {
  return {
    phase: "streaming",
    statusLabel: "Thinking",
    draftText: "Draft",
    activityItems: [
      {
        id: "activity_1",
        runId: "run_1",
        itemKey: "tool:call_1",
        kind: "tool",
        status: "completed",
        title: "Web search",
        summary: "Searching",
        sequence: 1,
        payload: {},
        createdAt: "2026-01-01T00:00:00.000Z",
        updatedAt: "2026-01-01T00:00:00.000Z",
      },
    ],
    content: [{ type: "text", text: "Draft" }],
    liveMessage: null,
    runId: "run_1",
    runMessageId: "msg_1",
    assistantMessageId: "assist_1",
    ...overrides,
  };
}

function makeAuthoritative(overrides?: Partial<AuthoritativeStreamSnapshot>): AuthoritativeStreamSnapshot {
  return {
    status: "running",
    runId: "run_1",
    runMessageId: "msg_1",
    currentStep: "Thinking",
    assistantMessageId: "assist_1",
    resumeSinceStreamEventId: 12,
    activityCursor: 1,
    pendingRequests: [],
    draftText: "Draft",
    activityItems: makeStream().activityItems,
    liveMessage: null,
    queuedTurns: [],
    ...overrides,
  };
}

describe("authoritative sync helpers", () => {
  it("does not rehydrate when running snapshot matches local stream", () => {
    expect(shouldHydrateRunningSnapshot({
      stream: makeStream(),
      authoritative: makeAuthoritative(),
      localLastEventId: 12,
    })).toBe(false);
  });

  it("rehydrates running snapshot when authoritative draft advances", () => {
    expect(shouldHydrateRunningSnapshot({
      stream: makeStream(),
      authoritative: makeAuthoritative({ draftText: "Draft plus more" }),
      localLastEventId: 12,
    })).toBe(true);
  });

  it("rehydrates when the authoritative run identity changes", () => {
    expect(shouldHydrateRunningSnapshot({
      stream: makeStream(),
      authoritative: makeAuthoritative({
        runId: "run_2",
        runMessageId: "msg_2",
        assistantMessageId: "assist_2",
      }),
      localLastEventId: 12,
    })).toBe(true);
  });

  it("does not rehydrate when authoritative runtime is behind the local live stream", () => {
    expect(shouldHydrateRunningSnapshot({
      stream: makeStream({
        draftText: "Draft plus more",
        activityItems: [
          ...makeStream().activityItems,
          {
            id: "activity_2",
            runId: "run_1",
            itemKey: "tool:call_2",
            kind: "tool",
            status: "running",
            title: "Code execution",
            summary: "Running query",
            sequence: 2,
            payload: {},
            createdAt: "2026-01-01T00:00:01.000Z",
            updatedAt: "2026-01-01T00:00:01.000Z",
          },
        ],
      }),
      authoritative: makeAuthoritative({
        resumeSinceStreamEventId: 8,
        activityCursor: 1,
      }),
      localLastEventId: 12,
    })).toBe(false);
  });

  it("rehydrates when the authoritative snapshot is current but has less local transient detail", () => {
    expect(shouldHydrateRunningSnapshot({
      stream: makeStream({
        draftText: "Draft plus more",
        activityItems: [
          ...makeStream().activityItems,
          {
            id: "activity_2",
            runId: "run_1",
            itemKey: "tool:call_2",
            kind: "tool",
            status: "running",
            title: "Code execution",
            summary: "Running query",
            sequence: 2,
            payload: {},
            createdAt: "2026-01-01T00:00:01.000Z",
            updatedAt: "2026-01-01T00:00:01.000Z",
          },
        ],
      }),
      authoritative: makeAuthoritative({
        draftText: "Draft",
        activityItems: makeStream().activityItems,
        resumeSinceStreamEventId: 12,
        activityCursor: 12,
      }),
      localLastEventId: 12,
    })).toBe(true);
  });

  it("rehydrates paused snapshot when pending input differs", () => {
    expect(shouldHydratePausedSnapshot({
      stream: makeStream({
        phase: "paused_for_input",
        statusLabel: "Waiting for your input",
      }),
      inputGate: {
        isPausedForInput: true,
        pausedPayload: {
          conversationId: "conv_1",
          messageId: "assist_1",
          requests: [],
        },
      },
      authoritative: makeAuthoritative({
        status: "paused",
        currentStep: "Waiting for your input",
        pendingRequests: [
          {
            callId: "call_1",
            toolName: "request_user_input",
            request: {
              tool: "request_user_input",
              title: "Need more detail",
              prompt: "Choose one option.",
              questions: [
                {
                  id: "scope",
                  question: "Need more detail?",
                  options: [
                    { label: "Short", description: "Keep the response brief." },
                    { label: "Detailed", description: "Expand the answer." },
                  ],
                },
              ],
            },
            result: {
              status: "pending",
              interaction_type: "user_input",
              request: {
                tool: "request_user_input",
                title: "Need more detail",
                prompt: "Choose one option.",
                questions: [
                  {
                    id: "scope",
                    question: "Need more detail?",
                    options: [
                      { label: "Short", description: "Keep the response brief." },
                      { label: "Detailed", description: "Expand the answer." },
                    ],
                  },
                ],
              },
            },
          },
        ],
      }),
    })).toBe(true);
  });
});
