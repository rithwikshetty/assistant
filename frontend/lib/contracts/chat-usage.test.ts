import { describe, expect, it } from "vitest";

import {
  parseConversationContextUsage,
  parseRunUsagePayload,
} from "./chat-usage";

describe("chat usage contracts", () => {
  it("parses conversation usage payloads into canonical numeric values", () => {
    expect(
      parseConversationContextUsage({
        input_tokens: "120",
        peak_context_tokens: 420.4,
        source: "stream",
      }),
    ).toEqual({
      input_tokens: 120,
      peak_context_tokens: 420,
      source: "stream",
    });
  });

  it("parses run usage payloads into canonical numeric values", () => {
    expect(
      parseRunUsagePayload({
        input_tokens: "200",
        cache_read_input_tokens: 25,
        aggregated_total_tokens: 410.2,
      }),
    ).toEqual({
      input_tokens: 200,
      cache_read_input_tokens: 25,
      aggregated_total_tokens: 410,
    });
  });
});
