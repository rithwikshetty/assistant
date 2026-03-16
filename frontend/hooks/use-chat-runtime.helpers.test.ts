import { describe, expect, it } from "vitest";
import type { Message } from "@/lib/chat/runtime/types";
import {
  buildStreamingTimeline,
  buildTranscriptTimeline,
  mapTransportPendingRequests,
} from "./use-chat-runtime.helpers";

describe("use-chat-runtime helpers", () => {
  it("maps pending transport requests and filters malformed entries", () => {
    const mapped = mapTransportPendingRequests([
      {
        call_id: "call_1",
        tool_name: "request_user_input",
        request: {
          tool: "request_user_input",
          title: "Approve scope",
          prompt: "Choose one path.",
          questions: [
            {
              id: "scope",
              question: "Which scope?",
              options: [
                { label: "Core", description: "Ship the smallest safe scope." },
                { label: "Full", description: "Cover the whole workflow now." },
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
            prompt: "Choose one path.",
            questions: [
              {
                id: "scope",
                question: "Which scope?",
                options: [
                  { label: "Core", description: "Ship the smallest safe scope." },
                  { label: "Full", description: "Cover the whole workflow now." },
                ],
              },
            ],
          },
        },
      },
    ]);

    expect(mapped).toEqual([
      {
        callId: "call_1",
        toolName: "request_user_input",
        request: {
          tool: "request_user_input",
          title: "Approve scope",
          prompt: "Choose one path.",
          questions: [
            {
              id: "scope",
              question: "Which scope?",
              options: [
                { label: "Core", description: "Ship the smallest safe scope." },
                { label: "Full", description: "Cover the whole workflow now." },
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
            prompt: "Choose one path.",
            questions: [
              {
                id: "scope",
                question: "Which scope?",
                options: [
                  { label: "Core", description: "Ship the smallest safe scope." },
                  { label: "Full", description: "Cover the whole workflow now." },
                ],
              },
            ],
          },
        },
      },
    ]);
  });

  it("keeps transcript timeline free of in-progress assistant rows", () => {
    const userMessage: Message = {
      id: "user_1",
      role: "user",
      content: [{ type: "text", text: "Hello" }],
      createdAt: new Date("2026-01-01T00:00:00.000Z"),
      status: "completed",
    };
    const inProgressAssistant: Message = {
      id: "assist_streaming",
      role: "assistant",
      content: [{ type: "text", text: "Working on it" }],
      createdAt: new Date("2026-01-01T00:00:01.000Z"),
      status: "streaming",
    };
    const finalAssistant: Message = {
      id: "assist_done",
      role: "assistant",
      content: [{ type: "text", text: "Done" }],
      createdAt: new Date("2026-01-01T00:00:02.000Z"),
      status: "completed",
    };

    expect(buildTranscriptTimeline([userMessage, inProgressAssistant, finalAssistant])).toEqual([
      userMessage,
      finalAssistant,
    ]);
  });

  it("keeps the persisted transient assistant row visible until a matching live stream is hydrated", () => {
    const streamingAssistant: Message = {
      id: "assist_streaming",
      role: "assistant",
      content: [{ type: "text", text: "Still working" }],
      createdAt: new Date("2026-01-01T00:00:01.000Z"),
      status: "streaming",
      metadata: {
        run_id: "run_1",
      },
    };

    expect(
      buildTranscriptTimeline(
        [streamingAssistant],
        {
          phase: "idle",
          statusLabel: null,
          draftText: "",
          activityItems: [],
          content: [],
          liveMessage: null,
          runId: null,
          runMessageId: null,
          assistantMessageId: null,
        },
      ),
    ).toEqual([streamingAssistant]);
  });

  it("appends the active assistant turn into the rendered timeline", () => {
    const timeline = buildStreamingTimeline({
      conversationId: "conv_1",
      messages: [
        {
          id: "user_1",
          role: "user",
          content: [{ type: "text", text: "Hello" }],
          createdAt: new Date("2026-01-01T00:00:00.000Z"),
          status: "completed",
        },
      ],
      stream: {
        phase: "streaming",
        statusLabel: "Writing response",
        draftText: "Working through the benchmark.",
        activityItems: [],
        content: [{ type: "text", text: "Working through the benchmark.", phase: "final" }],
        liveMessage: {
          id: "assist_streaming",
          role: "assistant",
          content: [{ type: "text", text: "Working through the benchmark.", phase: "final" }],
          activityItems: [],
          createdAt: new Date("2026-01-01T00:00:02.000Z"),
          metadata: {
            run_id: "run_1",
            payload: {
              text: "Working through the benchmark.",
              status: "running",
            },
          },
          status: "streaming",
        },
        runId: "run_1",
        runMessageId: "msg_1",
        assistantMessageId: "assist_streaming",
      },
      streamDisplay: {
        isStreaming: true,
        status: {
          phase: "responding",
          label: "Writing response",
        },
      },
      isPausedForInput: false,
    });

    expect(timeline).toHaveLength(2);
    expect(timeline[1]).toMatchObject({
      id: "assist_streaming",
      role: "assistant",
      status: "streaming",
      streamingStatus: {
        label: "Writing response",
      },
      metadata: {
        run_id: "run_1",
        live_message: true,
      },
    });
  });

  it("falls back to a minimal placeholder when no authoritative live message exists yet", () => {
    const timeline = buildStreamingTimeline({
      conversationId: "conv_1",
      messages: [],
      stream: {
        phase: "starting",
        statusLabel: "Writing response",
        draftText: "Draft reply",
        activityItems: [
          {
            id: "activity_1",
            runId: "run_1",
            itemKey: "tool:call_1",
            kind: "tool",
            status: "running",
            title: "Web search",
            summary: "Looking up source",
            sequence: 1,
            payload: {},
            createdAt: "2026-01-01T00:00:00.000Z",
            updatedAt: "2026-01-01T00:00:00.000Z",
          },
        ],
        content: [{ type: "text", text: "Draft reply", phase: "final" }],
        liveMessage: null,
        runId: "run_1",
        runMessageId: "msg_1",
        assistantMessageId: null,
      },
      streamDisplay: {
        isStreaming: true,
        status: {
          phase: "responding",
          label: "Writing response",
        },
      },
      isPausedForInput: false,
    });

    expect(timeline).toHaveLength(1);
    expect(timeline[0]).toMatchObject({
      id: "run_1",
      content: [{ type: "text", text: "Draft reply", phase: "final" }],
      activityItems: [
        expect.objectContaining({
          id: "activity_1",
          itemKey: "tool:call_1",
        }),
      ],
      metadata: {
        synthetic_stream: true,
        payload: {
          run_id: "run_1",
          text: "Draft reply",
          status: "streaming",
        },
      },
    });
  });
});
