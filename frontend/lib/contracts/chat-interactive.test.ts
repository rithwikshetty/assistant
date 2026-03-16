import { describe, expect, it } from "vitest";

import {
  parseRequestUserInputResultPayload,
} from "./chat-interactive";
import {
  parseToolRequestPayloadForTool,
  parseToolResultPayloadForTool,
} from "./chat-tool-payloads";

describe("chat interactive contracts", () => {
  it("parses completed request-user-input results", () => {
    expect(
      parseRequestUserInputResultPayload({
        status: "completed",
        interaction_type: "user_input",
        request: {
          tool: "request_user_input",
          title: "Need context",
          prompt: "Pick one",
          questions: [
            {
              id: "q1",
              question: "Priority?",
              options: [
                { label: "Fast", description: "Move quickly with a lean answer" },
                { label: "Deep", description: "Spend longer for a fuller analysis" },
              ],
            },
          ],
        },
        answers: [{ question_id: "q1", option_label: "Fast" }],
        custom_response: "Keep it concise.",
      }),
    ).toMatchObject({
      status: "completed",
      answers: [{ question_id: "q1", option_label: "Fast" }],
      custom_response: "Keep it concise.",
    });
  });

  it("routes request-user-input payloads through the public helper", () => {
    expect(
      parseToolRequestPayloadForTool("request_user_input", {
        tool: "request_user_input",
        title: "Need context",
        prompt: "Pick one",
        questions: [
          {
            id: "q1",
            question: "Priority?",
            options: [
              { label: "Fast", description: "Move quickly with a lean answer" },
              { label: "Deep", description: "Spend longer for a fuller analysis" },
            ],
          },
        ],
      }),
    ).toMatchObject({
      tool: "request_user_input",
      title: "Need context",
    });
  });

  it("routes interactive request/result parsing through the public tool-aware helpers", () => {
    expect(
      parseToolResultPayloadForTool("request_user_input", {
        status: "completed",
        interaction_type: "user_input",
        request: {
          tool: "request_user_input",
          title: "Need context",
          prompt: "Pick one",
          questions: [
            {
              id: "q1",
              question: "Priority?",
              options: [
                { label: "Fast", description: "Move quickly with a lean answer" },
                { label: "Deep", description: "Spend longer for a fuller analysis" },
              ],
            },
          ],
        },
        answers: [{ question_id: "q1", option_label: "Fast" }],
      }),
    ).toMatchObject({
      status: "completed",
      answers: [{ question_id: "q1", option_label: "Fast" }],
    });
  });
});
