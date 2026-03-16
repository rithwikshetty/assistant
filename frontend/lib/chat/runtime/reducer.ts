import type { Message, RunActivityItem, StreamPhase, StreamSlice } from "@/lib/chat/runtime/types";
import {
  projectStreamContent,
} from "@/lib/chat/runtime/activity";
import { resolveMessageText } from "@/lib/chat/runtime/timeline-repo";
import type { TimelineMessagePayload } from "@/lib/contracts/chat";

export type StreamRuntimeState = StreamSlice & {
  error: Error | null;
};

export type StreamRuntimeAction =
  | { type: "reset" }
  | {
      type: "hydrate_runtime";
      phase: StreamPhase;
      statusLabel?: string | null;
      draftText?: string | null;
      activityItems?: RunActivityItem[];
      liveMessage?: Message | null;
      runId?: string | null;
      runMessageId?: string | null;
      assistantMessageId?: string | null;
    }
  | {
      type: "set_phase";
      phase: StreamPhase;
      statusLabel?: string | null;
      runId?: string | null;
      runMessageId?: string | null;
      assistantMessageId?: string | null;
    }
  | { type: "set_status"; statusLabel: string | null }
  | { type: "append_delta"; delta: string; statusLabel?: string | null }
  | { type: "set_activity_items"; activityItems: RunActivityItem[] }
  | { type: "set_error"; error: Error | null }
  | {
      type: "set_run_context";
      runId?: string | null;
      runMessageId?: string | null;
      assistantMessageId?: string | null;
    };

function reprojectLiveMessage(args: {
  liveMessage: Message | null;
  draftText: string;
  activityItems: RunActivityItem[];
}): Message | null {
  const { liveMessage, draftText, activityItems } = args;
  if (!liveMessage) return null;

  const payload: TimelineMessagePayload = liveMessage.metadata?.payload ?? {};

  return {
    ...liveMessage,
    content: projectStreamContent({
      draftText,
      activityItems,
    }),
    activityItems,
    metadata: {
      ...(liveMessage.metadata ?? {}),
      activity_item_count: activityItems.length,
      payload: {
        ...payload,
        text: draftText,
        ...(typeof liveMessage.status === "string" ? { status: liveMessage.status } : {}),
      },
    },
  };
}

function deriveContent(args: {
  draftText: string;
  activityItems: RunActivityItem[];
  liveMessage: Message | null;
}) {
  return args.liveMessage?.content ?? projectStreamContent({
    draftText: args.draftText,
    activityItems: args.activityItems,
  });
}

function resolveHydratedDraftText(args: {
  stateDraftText: string;
  actionDraftText?: string | null;
  liveMessage: Message | null;
}): string {
  const { stateDraftText, actionDraftText, liveMessage } = args;
  if (typeof actionDraftText === "string") {
    return actionDraftText;
  }
  if (liveMessage) {
    return resolveMessageText(liveMessage, true);
  }
  return stateDraftText;
}

export function createInitialStreamRuntimeState(): StreamRuntimeState {
  return {
    phase: "idle",
    statusLabel: null,
    draftText: "",
    activityItems: [],
    content: [],
    liveMessage: null,
    runId: null,
    runMessageId: null,
    assistantMessageId: null,
    error: null,
  };
}

export function streamRuntimeReducer(
  state: StreamRuntimeState,
  action: StreamRuntimeAction,
): StreamRuntimeState {
  switch (action.type) {
    case "reset":
      return createInitialStreamRuntimeState();
    case "hydrate_runtime":
      {
        const nextActivityItems =
          action.activityItems !== undefined ? action.activityItems : state.activityItems;
        const incomingLiveMessage =
          action.liveMessage !== undefined ? action.liveMessage : state.liveMessage;
        const resolvedDraftText = resolveHydratedDraftText({
          stateDraftText: state.draftText,
          actionDraftText: action.draftText,
          liveMessage: incomingLiveMessage,
        });
        const nextLiveMessage = reprojectLiveMessage({
          liveMessage: incomingLiveMessage,
          draftText: resolvedDraftText,
          activityItems: nextActivityItems,
        });
      return {
        ...state,
        phase: action.phase,
        statusLabel: action.statusLabel !== undefined ? action.statusLabel : state.statusLabel,
        draftText: resolvedDraftText,
        activityItems: nextActivityItems,
        content: deriveContent({
          draftText: resolvedDraftText,
          activityItems: nextActivityItems,
          liveMessage: nextLiveMessage,
        }),
        liveMessage: nextLiveMessage,
        runId: action.runId !== undefined ? action.runId : state.runId,
        runMessageId: action.runMessageId !== undefined ? action.runMessageId : state.runMessageId,
        assistantMessageId: action.assistantMessageId !== undefined ? action.assistantMessageId : state.assistantMessageId,
        error: null,
      };
      }
    case "set_phase":
      {
        const nextLiveMessage =
          action.assistantMessageId === null ||
          action.phase === "idle" ||
          action.phase === "error"
            ? null
            : state.liveMessage;
      return {
        ...state,
        phase: action.phase,
        statusLabel: action.statusLabel !== undefined ? action.statusLabel : state.statusLabel,
        content: deriveContent({
          draftText: state.draftText,
          activityItems: state.activityItems,
          liveMessage: nextLiveMessage,
        }),
        liveMessage: nextLiveMessage,
        runId: action.runId !== undefined ? action.runId : state.runId,
        runMessageId: action.runMessageId !== undefined ? action.runMessageId : state.runMessageId,
        assistantMessageId: action.assistantMessageId !== undefined ? action.assistantMessageId : state.assistantMessageId,
        error: action.phase === "error" ? state.error : null,
      };
      }
    case "set_status":
      return {
        ...state,
        statusLabel: action.statusLabel,
      };
    case "append_delta": {
      const nextDraftText = `${state.draftText}${action.delta}`;
      const nextLiveMessage = reprojectLiveMessage({
        liveMessage: state.liveMessage,
        draftText: nextDraftText,
        activityItems: state.activityItems,
      });
      return {
        ...state,
        phase: state.phase === "idle" ? "streaming" : state.phase,
        statusLabel: action.statusLabel !== undefined ? action.statusLabel : state.statusLabel,
        draftText: nextDraftText,
        content: deriveContent({
          draftText: nextDraftText,
          activityItems: state.activityItems,
          liveMessage: nextLiveMessage,
        }),
        liveMessage: nextLiveMessage,
      };
    }
    case "set_activity_items": {
      const nextLiveMessage = reprojectLiveMessage({
        liveMessage: state.liveMessage,
        draftText: state.draftText,
        activityItems: action.activityItems,
      });
      return {
        ...state,
        activityItems: action.activityItems,
        content: deriveContent({
          draftText: state.draftText,
          activityItems: action.activityItems,
          liveMessage: nextLiveMessage,
        }),
        liveMessage: nextLiveMessage,
      };
    }
    case "set_error":
      return {
        ...state,
        error: action.error,
      };
    case "set_run_context":
      return {
        ...state,
        liveMessage: action.assistantMessageId === null ? null : state.liveMessage,
        content: deriveContent({
          draftText: state.draftText,
          activityItems: state.activityItems,
          liveMessage: action.assistantMessageId === null ? null : state.liveMessage,
        }),
        runId: action.runId !== undefined ? action.runId : state.runId,
        runMessageId: action.runMessageId !== undefined ? action.runMessageId : state.runMessageId,
        assistantMessageId: action.assistantMessageId !== undefined ? action.assistantMessageId : state.assistantMessageId,
      };
    default:
      return state;
  }
}
