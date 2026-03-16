import { describe, expect, it } from "vitest";

import { KNOWN_MODEL_KEYS, formatModelName, getModelColor } from "./provider-display";

describe("provider display model mappings", () => {
  it("formats gpt-5.4 model labels", () => {
    expect(formatModelName("gpt-5.4")).toBe("GPT-5.4");
    expect(formatModelName("gpt-5.4-2026-03-05")).toBe("GPT-5.4");
  });

  it("formats unknown providers generically", () => {
    expect(formatModelName("azure")).toBe("Azure");
    expect(formatModelName("custom_provider")).toBe("Custom Provider");
  });

  it("uses OpenAI accent color for gpt-5.4", () => {
    expect(getModelColor("gpt-5.4")).toBe("var(--chart-3)");
  });

  it("exports known model keys for provider selectors", () => {
    expect(KNOWN_MODEL_KEYS).toEqual(["gpt-5.4"]);
  });
});
