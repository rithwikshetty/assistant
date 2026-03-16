import { describe, expect, it } from "vitest";

import { hasMeaningfulContextUsage, resolveContextTokensUsed } from "@/lib/chat/context-usage";

describe("resolveContextTokensUsed", () => {
  it("prefers explicit current context metric when present", () => {
    const used = resolveContextTokensUsed({
      input_tokens: 120,
      output_tokens: 30,
      total_tokens: 150,
      current_context_tokens: 140,
      max_context_tokens: 200000,
    });

    expect(used).toBe(140);
  });

  it("prefers total token metrics over input metrics", () => {
    const used = resolveContextTokensUsed({
      input_tokens: 120,
      output_tokens: 30,
      total_tokens: 150,
      max_context_tokens: 200000,
    });

    expect(used).toBe(150);
  });

  it("does not overcount with aggregated values when context metrics exist", () => {
    const used = resolveContextTokensUsed({
      input_tokens: 100,
      output_tokens: 0,
      total_tokens: 110,
      aggregated_total_tokens: 220,
      max_context_tokens: 200000,
    });

    expect(used).toBe(110);
  });

  it("falls back to aggregated metrics only when context metrics are missing", () => {
    const used = resolveContextTokensUsed({
      aggregated_total_tokens: 220,
      max_context_tokens: 200000,
    } as unknown as Parameters<typeof resolveContextTokensUsed>[0]);

    expect(used).toBe(220);
  });

  it("falls back to input when total metrics are unavailable", () => {
    const used = resolveContextTokensUsed({
      input_tokens: 95,
      output_tokens: 0,
      total_tokens: 0,
      max_context_tokens: 200000,
    });

    expect(used).toBe(95);
  });
});

describe("hasMeaningfulContextUsage", () => {
  it("returns false for zero-only snapshots", () => {
    expect(
      hasMeaningfulContextUsage({
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        max_context_tokens: 400000,
        remaining_context_tokens: 400000,
      }),
    ).toBe(false);
  });

  it("returns true for positive usage snapshots", () => {
    expect(
      hasMeaningfulContextUsage({
        input_tokens: 1200,
        output_tokens: 200,
        total_tokens: 1400,
      }),
    ).toBe(true);
  });
});
