import type { ConversationRuntimeResponse } from "@/lib/api/chat";
import type {
  AuthoritativeStreamSnapshot,
  QueuedTurn,
  RecheckAuthoritativeState,
} from "@/lib/chat/runtime/types";
import { mapActivityItemResponse, mapTimelineItem } from "@/lib/chat/runtime/timeline-repo";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import { mapTransportPendingRequests } from "./use-chat-runtime.helpers";

export function resolveAuthoritativeSnapshotFromRuntime(
  runtime: ConversationRuntimeResponse,
): AuthoritativeStreamSnapshot {
  const queuedTurnsRaw = Array.isArray(runtime.queued_turns) ? runtime.queued_turns : [];
  const queuedTurns: QueuedTurn[] = queuedTurnsRaw.map((item) => ({
    queuePosition: item.queue_position,
    runId: item.run_id,
    userMessageId: item.user_message_id,
    blockedByRunId: item.blocked_by_run_id ?? null,
    createdAt: item.created_at ?? null,
    text: null,
  }));

  const runId = normalizeNonEmptyString(runtime.run_id) ?? null;
  const runMessageId = normalizeNonEmptyString(runtime.run_message_id) ?? null;
  const currentStep = normalizeNonEmptyString(runtime.status_label) ?? null;
  const assistantMessageId = normalizeNonEmptyString(runtime.assistant_message_id) ?? null;
  const resumeSinceRaw = runtime.resume_since_stream_event_id ?? runtime.last_seq;
  const resumeSinceStreamEventId =
    typeof resumeSinceRaw === "number" && Number.isFinite(resumeSinceRaw)
      ? Math.max(0, Math.floor(resumeSinceRaw))
      : 0;
  const activityCursorRaw = runtime.activity_cursor ?? runtime.last_seq;
  const activityCursor =
    typeof activityCursorRaw === "number" && Number.isFinite(activityCursorRaw)
      ? Math.max(0, Math.floor(activityCursorRaw))
      : 0;
  const pendingRequests = mapTransportPendingRequests(runtime.pending_requests);
  const liveMessage = runtime.live_message ? mapTimelineItem(runtime.live_message) : null;
  const rawActivityItems = Array.isArray(runtime.activity_items) ? runtime.activity_items : [];

  const rawStatus = normalizeNonEmptyString(runtime.status)?.toLowerCase() ?? "";
  const active = runtime.active === true;
  const status: RecheckAuthoritativeState =
    rawStatus === "paused"
      ? "paused"
      : rawStatus === "running" || active
        ? "running"
        : "idle";

  return {
    status,
    runId,
    runMessageId,
    currentStep,
    assistantMessageId,
    resumeSinceStreamEventId,
    activityCursor,
    pendingRequests,
    draftText: typeof runtime.draft_text === "string" ? runtime.draft_text : "",
    activityItems: rawActivityItems.map(mapActivityItemResponse),
    liveMessage,
    queuedTurns,
  };
}
