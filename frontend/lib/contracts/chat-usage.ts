import {
  type JsonRecord,
  expectRecord,
  readNullableString,
} from "./contract-utils";

export interface ConversationContextUsage {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  current_context_tokens?: number;
  peak_context_tokens?: number;
  max_context_tokens?: number;
  remaining_context_tokens?: number;
  aggregated_input_tokens?: number;
  aggregated_output_tokens?: number;
  aggregated_total_tokens?: number;
  cumulative_input_tokens?: number;
  cumulative_output_tokens?: number;
  cumulative_total_tokens?: number;
  compact_trigger_tokens?: number;
  source?: string;
}

export interface RunUsagePayload {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  base_input_tokens?: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
  max_context_tokens?: number;
  remaining_context_tokens?: number;
  aggregated_input_tokens?: number;
  aggregated_output_tokens?: number;
  aggregated_total_tokens?: number;
}

type ConversationContextUsageNumericKey =
  | "input_tokens"
  | "output_tokens"
  | "total_tokens"
  | "current_context_tokens"
  | "peak_context_tokens"
  | "max_context_tokens"
  | "remaining_context_tokens"
  | "aggregated_input_tokens"
  | "aggregated_output_tokens"
  | "aggregated_total_tokens"
  | "cumulative_input_tokens"
  | "cumulative_output_tokens"
  | "cumulative_total_tokens"
  | "compact_trigger_tokens";

type RunUsagePayloadNumericKey =
  | "input_tokens"
  | "output_tokens"
  | "total_tokens"
  | "base_input_tokens"
  | "cache_creation_input_tokens"
  | "cache_read_input_tokens"
  | "max_context_tokens"
  | "remaining_context_tokens"
  | "aggregated_input_tokens"
  | "aggregated_output_tokens"
  | "aggregated_total_tokens";

function readNumberLike(record: JsonRecord, key: string, label: string): number | undefined {
  const value = record[key];
  if (value == null) return undefined;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  throw new Error(`${label}.${key} must be numeric`);
}

function readNonNegativeInt(value: number): number {
  return Math.max(0, Math.round(value));
}

export function parseConversationContextUsage(
  raw: unknown,
  label: string = "conversationContextUsage",
): ConversationContextUsage {
  const record = expectRecord(raw, label);
  const result: ConversationContextUsage = {};
  const numericKeys: ConversationContextUsageNumericKey[] = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "current_context_tokens",
    "peak_context_tokens",
    "max_context_tokens",
    "remaining_context_tokens",
    "aggregated_input_tokens",
    "aggregated_output_tokens",
    "aggregated_total_tokens",
    "cumulative_input_tokens",
    "cumulative_output_tokens",
    "cumulative_total_tokens",
    "compact_trigger_tokens",
  ];

  for (const key of numericKeys) {
    const parsed = readNumberLike(record, key, label);
    if (parsed != null) {
      result[key] = readNonNegativeInt(parsed);
    }
  }

  const source = readNullableString(record, "source", label);
  if (typeof source === "string") {
    result.source = source;
  }

  return result;
}

export function parseRunUsagePayload(
  raw: unknown,
  label: string = "runUsage",
): RunUsagePayload {
  const record = expectRecord(raw, label);
  const result: RunUsagePayload = {};
  const numericKeys: RunUsagePayloadNumericKey[] = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "base_input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "max_context_tokens",
    "remaining_context_tokens",
    "aggregated_input_tokens",
    "aggregated_output_tokens",
    "aggregated_total_tokens",
  ];

  for (const key of numericKeys) {
    const parsed = readNumberLike(record, key, label);
    if (parsed != null) {
      result[key] = readNonNegativeInt(parsed);
    }
  }

  return result;
}
