import { describe, expect, it } from "vitest";

import { parseChatUserEvent } from "./ws-user-events";

describe("parseChatUserEvent", () => {
  it("parses canonical initial_state payloads", () => {
    expect(
      parseChatUserEvent({
        type: "initial_state",
        streams: [
          {
            conversation_id: "conv_1",
            user_message_id: "msg_1",
            run_id: "run_1",
            started_at: "2026-03-13T00:00:00Z",
            current_step: "Thinking",
          },
        ],
      }),
    ).toEqual({
      type: "initial_state",
      streams: [
        {
          conversation_id: "conv_1",
          user_message_id: "msg_1",
          run_id: "run_1",
          started_at: "2026-03-13T00:00:00Z",
          current_step: "Thinking",
        },
      ],
    });
  });

  it("rejects unsupported internal-only lifecycle events", () => {
    expect(
      parseChatUserEvent({
        type: "stream_registered",
        conversation_id: "conv_1",
      }),
    ).toBeNull();
  });

  it("requires canonical title update payloads", () => {
    expect(
      parseChatUserEvent({
        type: "conversation_title_updated",
        conversation_id: "conv_1",
        title: "Retitled chat",
        updated_at: "2026-03-13T00:00:00Z",
      }),
    ).toEqual({
      type: "conversation_title_updated",
      conversation_id: "conv_1",
      title: "Retitled chat",
      updated_at: "2026-03-13T00:00:00Z",
      source: undefined,
    });
  });
});
