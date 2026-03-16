import type { ChatMessageContentPart } from "@/lib/chat/content-parts";
import { getToolDisplayName } from "@/lib/tools/constants";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";

export type StreamingPhase =
  | "idle"
  | "starting"
  | "model"
  | "tool"
  | "responding"
  | "awaiting_input";

export type StreamingStatusState = {
  phase: StreamingPhase;
  label: string | null;
};

export const STREAMING_STATUS_IDLE: StreamingStatusState = { phase: "idle", label: null };
export const STREAMING_STATUS_STARTING: StreamingStatusState = { phase: "starting", label: "Starting" };
export const STREAMING_STATUS_MODEL: StreamingStatusState = { phase: "model", label: "Thinking" };
export const STREAMING_STATUS_RESPONDING: StreamingStatusState = { phase: "responding", label: "Writing response" };
export const STREAMING_STATUS_AWAITING_INPUT: StreamingStatusState = {
  phase: "awaiting_input",
  label: "Waiting for your input",
};

function normalizeToolName(raw: unknown): string | null {
  return normalizeNonEmptyString(raw);
}

function toFriendlyToolLabel(toolName: string | null): string {
  if (!toolName) return "Using tool";
  if (toolName === "request_user_input") return "Preparing input prompt";
  const readable = getToolDisplayName(toolName).trim();
  return readable.length > 0 ? `Using ${readable}` : "Using tool";
}

function getOpenToolName(contentParts: ChatMessageContentPart[]): string | null {
  for (let i = contentParts.length - 1; i >= 0; i--) {
    const part = contentParts[i];
    if (part.type !== "tool-call") continue;
    if (part.result !== undefined || part.isError === true) continue;
    return normalizeToolName(part.toolName);
  }
  return null;
}

export function deriveStreamingStatusFromContent(contentParts: ChatMessageContentPart[]): StreamingStatusState {
  const openToolName = getOpenToolName(contentParts);
  if (openToolName) {
    return { phase: "tool", label: toFriendlyToolLabel(openToolName) };
  }

  const hasVisibleText = contentParts.some(
    (part) => part.type === "text" && part.text.trim().length > 0,
  );
  if (hasVisibleText) return STREAMING_STATUS_RESPONDING;
  return STREAMING_STATUS_MODEL;
}

export function resolveStreamingStatusFromCurrentStep(
  step: string | null | undefined,
): StreamingStatusState | null {
  if (typeof step !== "string") return null;
  const normalized = step.trim();
  if (!normalized) return null;

  const lowered = normalized.toLowerCase();
  if (lowered.includes("waiting for your input") || lowered.includes("awaiting input")) {
    return STREAMING_STATUS_AWAITING_INPUT;
  }
  if (lowered.includes("starting")) {
    return STREAMING_STATUS_STARTING;
  }
  if (lowered.includes("using ") || lowered.includes("tool") || lowered.includes("preparing input prompt")) {
    return { phase: "tool", label: normalized };
  }
  if (lowered.includes("generating") || lowered.includes("writing")) {
    return STREAMING_STATUS_RESPONDING;
  }
  if (lowered.includes("thinking") || lowered.includes("rendering") || lowered.includes("model")) {
    return STREAMING_STATUS_MODEL;
  }
  return { phase: "model", label: normalized };
}
