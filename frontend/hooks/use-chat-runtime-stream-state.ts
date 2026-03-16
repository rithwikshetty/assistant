import type { Dispatch, SetStateAction } from "react";
import type { StreamRuntimeAction } from "@/lib/chat/runtime/reducer";
import type { Message, RunActivityItem, UserInputPayload } from "@/lib/chat/runtime/types";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import { STREAMING_STATUS_AWAITING_INPUT, STREAMING_STATUS_STARTING } from "@/lib/chat/streaming-status";
import type { InputGateState } from "./use-chat-runtime-stream.types";

export type ResolveReconnectSnapshotOptions = {
  runId?: string | null;
  runMessageId?: string | null;
  resumeSinceStreamEventId?: number;
  statusLabel?: string | null;
  assistantMessageId?: string | null;
  draftText?: string | null;
  activityItems?: RunActivityItem[];
};

export type StreamReconnectSnapshot = {
  runId: string | null;
  runMessageId: string | null;
  assistantMessageId: string | null;
  sinceStreamEventId: number;
  draftText: string;
  activityItems: RunActivityItem[];
  statusLabel: string | null;
};

export type HydratePausedStateOptions = {
  runId: string | null;
  runMessageId: string | null;
  pendingRequests: UserInputPayload["requests"];
  assistantMessageId: string | null;
  statusLabel?: string | null;
  draftText?: string | null;
  activityItems?: RunActivityItem[];
  liveMessage?: Message | null;
};

export type HydratePausedStateArgs = {
  conversationId: string;
  options: HydratePausedStateOptions;
  dispatch: Dispatch<StreamRuntimeAction>;
  setInputGate: Dispatch<SetStateAction<InputGateState>>;
  markLocalPause: (conversationId: string) => void;
};

export function resolveReconnectSnapshot(args: {
  conversationId: string;
  runId: string | null;
  runMessageId: string | null;
  draftText: string;
  activityItems: RunActivityItem[];
  currentStatusLabel: string | null;
  options?: ResolveReconnectSnapshotOptions;
}): StreamReconnectSnapshot {
  const { runId, runMessageId, draftText, activityItems, currentStatusLabel, options } = args;
  const sinceStreamEventId =
    typeof options?.resumeSinceStreamEventId === "number" && Number.isFinite(options.resumeSinceStreamEventId)
      ? Math.max(0, Math.floor(options.resumeSinceStreamEventId))
      : 0;

  const resolvedStatus =
    normalizeNonEmptyString(options?.statusLabel) ??
    normalizeNonEmptyString(currentStatusLabel) ??
    (draftText.length > 0 || activityItems.length > 0 ? "Working" : STREAMING_STATUS_STARTING.label);

  return {
    runId: normalizeNonEmptyString(options?.runId) ?? normalizeNonEmptyString(runId),
    runMessageId: normalizeNonEmptyString(options?.runMessageId) ?? normalizeNonEmptyString(runMessageId),
    assistantMessageId: normalizeNonEmptyString(options?.assistantMessageId),
    sinceStreamEventId,
    draftText: typeof options?.draftText === "string" ? options.draftText : draftText,
    activityItems: Array.isArray(options?.activityItems) ? options.activityItems : activityItems,
    statusLabel: resolvedStatus,
  };
}

export async function hydratePausedState(args: HydratePausedStateArgs): Promise<void> {
  const {
    conversationId,
    options,
    dispatch,
    setInputGate,
    markLocalPause,
  } = args;

  dispatch({
    type: "hydrate_runtime",
    phase: "paused_for_input",
    statusLabel: options.statusLabel ?? STREAMING_STATUS_AWAITING_INPUT.label,
    draftText: options.draftText ?? "",
    activityItems: options.activityItems ?? [],
    liveMessage: options.liveMessage,
    runId: options.runId,
    runMessageId: options.runMessageId,
    assistantMessageId: options.assistantMessageId,
  });

  const pausedMessageId =
    options.assistantMessageId ??
    options.runMessageId ??
    `pending-${conversationId}`;

  if (options.pendingRequests.length > 0) {
    setInputGate({
      isPausedForInput: true,
      pausedPayload: {
        conversationId,
        runId: options.runId,
        messageId: pausedMessageId,
        requests: options.pendingRequests,
      },
    });
  } else {
    setInputGate({ isPausedForInput: false, pausedPayload: null });
  }

  markLocalPause(conversationId);
}
