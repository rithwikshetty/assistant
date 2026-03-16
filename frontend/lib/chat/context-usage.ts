import type { ConversationContextUsage } from "@/lib/api/auth";

function coerceNonNegativeInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(0, Math.round(value));
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return Math.max(0, Math.round(parsed));
    }
  }
  return null;
}

/**
 * Best-effort estimate of active context tokens currently occupied.
 *
 * Prefer total token figures when available, because context growth across turns
 * includes both prompt/input and assistant output.
 */
export function resolveContextTokensUsed(
  usage: ConversationContextUsage | null | undefined,
): number | null {
  if (!usage) return null;

  const current = coerceNonNegativeInt(usage.current_context_tokens);
  if (current !== null) {
    return current;
  }

  const total = coerceNonNegativeInt(usage.total_tokens);
  const input = coerceNonNegativeInt(usage.input_tokens);

  if (total !== null && total > 0) {
    return total;
  }
  if (input !== null && input > 0) {
    return input;
  }
  if (total !== null) {
    return total;
  }
  if (input !== null) {
    return input;
  }

  const fallbackCandidates = [
    coerceNonNegativeInt(usage.aggregated_total_tokens),
    coerceNonNegativeInt(usage.aggregated_input_tokens),
  ].filter((value): value is number => value !== null);

  if (fallbackCandidates.length === 0) return null;
  return fallbackCandidates[0];
}

export function hasMeaningfulContextUsage(
  usage: ConversationContextUsage | null | undefined,
): boolean {
  if (!usage) return false;
  const candidates = [
    coerceNonNegativeInt(usage.current_context_tokens),
    coerceNonNegativeInt(usage.peak_context_tokens),
    coerceNonNegativeInt(usage.total_tokens),
    coerceNonNegativeInt(usage.aggregated_total_tokens),
    coerceNonNegativeInt(usage.input_tokens),
    coerceNonNegativeInt(usage.aggregated_input_tokens),
    coerceNonNegativeInt(usage.cumulative_total_tokens),
    coerceNonNegativeInt(usage.cumulative_input_tokens),
    coerceNonNegativeInt(usage.output_tokens),
    coerceNonNegativeInt(usage.cumulative_output_tokens),
  ].filter((value): value is number => value !== null);

  if (candidates.length === 0) return false;
  return Math.max(...candidates) > 0;
}
