import { describe, expect, it } from "vitest";

import { parseToolErrorPayload } from "./chat-tool-errors";

describe("chat-tool-errors", () => {
  it("parses canonical tool error payloads", () => {
    expect(
      parseToolErrorPayload({
        message: "Query failed",
        code: "QUERY_FAILED",
      }),
    ).toEqual({
      message: "Query failed",
      code: "QUERY_FAILED",
    });
  });
});
