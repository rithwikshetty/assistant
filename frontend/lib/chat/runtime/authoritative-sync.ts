import type {
  AuthoritativeStreamSnapshot,
  InputGateSlice,
  RunActivityItem,
  StreamRenderSlice,
  UserInputPayload,
} from "@/lib/chat/runtime/types";

function isSameActivityItem(left: RunActivityItem, right: RunActivityItem): boolean {
  return (
    left.id === right.id &&
    left.itemKey === right.itemKey &&
    left.status === right.status &&
    left.sequence === right.sequence &&
    left.updatedAt === right.updatedAt &&
    left.title === right.title &&
    left.summary === right.summary
  );
}

function areSameActivityItems(left: RunActivityItem[], right: RunActivityItem[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((item, index) => isSameActivityItem(item, right[index]!));
}

function isSamePendingRequest(
  left: UserInputPayload["requests"][number],
  right: UserInputPayload["requests"][number],
): boolean {
  return (
    left.callId === right.callId &&
    left.toolName === right.toolName &&
    JSON.stringify(left.request) === JSON.stringify(right.request) &&
    JSON.stringify(left.result) === JSON.stringify(right.result)
  );
}

function areSamePendingRequests(
  left: UserInputPayload["requests"],
  right: UserInputPayload["requests"],
): boolean {
  if (left.length !== right.length) return false;
  return left.every((request, index) => isSamePendingRequest(request, right[index]!));
}

function isSameLiveMessage(
  left: AuthoritativeStreamSnapshot["liveMessage"],
  right: AuthoritativeStreamSnapshot["liveMessage"],
): boolean {
  if (left === right) return true;
  if (!left || !right) return false;
  return (
    left.id === right.id &&
    left.status === right.status &&
    left.createdAt.getTime() === right.createdAt.getTime() &&
    JSON.stringify(left.content) === JSON.stringify(right.content)
  );
}

function authoritativeProgressValue(authoritative: AuthoritativeStreamSnapshot): number {
  return Math.max(authoritative.resumeSinceStreamEventId, authoritative.activityCursor);
}

export function shouldHydrateRunningSnapshot(args: {
  stream: StreamRenderSlice;
  authoritative: AuthoritativeStreamSnapshot;
  localLastEventId: number;
}): boolean {
  const { stream, authoritative, localLastEventId } = args;
  if (authoritative.status !== "running") return false;

  const localIsActive =
    stream.phase === "starting" ||
    stream.phase === "streaming" ||
    stream.phase === "completing";
  const sameRun =
    stream.runId === authoritative.runId &&
    stream.runMessageId === authoritative.runMessageId;
  const authoritativeProgress = authoritativeProgressValue(authoritative);

  if (localIsActive && sameRun) {
    if (localLastEventId > authoritativeProgress) {
      return false;
    }
  }

  // Don't consider a statusLabel difference as a reason to hydrate when the
  // authoritative currentStep is empty — it would overwrite a meaningful local
  // label (e.g. "Starting") with null, causing the streaming message to vanish.
  const statusLabelDiffers =
    stream.statusLabel !== authoritative.currentStep &&
    authoritative.currentStep != null;

  return (
    stream.phase !== "streaming" &&
    stream.phase !== "starting" &&
    stream.phase !== "completing"
  ) || (
    stream.runId !== authoritative.runId ||
    stream.runMessageId !== authoritative.runMessageId ||
    stream.assistantMessageId !== authoritative.assistantMessageId ||
    statusLabelDiffers ||
    !isSameLiveMessage(stream.liveMessage, authoritative.liveMessage) ||
    stream.draftText !== authoritative.draftText ||
    !areSameActivityItems(stream.activityItems, authoritative.activityItems)
  );
}

export function shouldHydratePausedSnapshot(args: {
  stream: StreamRenderSlice;
  inputGate: InputGateSlice;
  authoritative: AuthoritativeStreamSnapshot;
}): boolean {
  const { stream, inputGate, authoritative } = args;
  if (authoritative.status !== "paused") return false;
  const pendingRequests = inputGate.pausedPayload?.requests ?? [];
  return (
    stream.phase !== "paused_for_input" ||
    !inputGate.isPausedForInput ||
    stream.runId !== authoritative.runId ||
    stream.runMessageId !== authoritative.runMessageId ||
    stream.assistantMessageId !== authoritative.assistantMessageId ||
    stream.statusLabel !== authoritative.currentStep ||
    !isSameLiveMessage(stream.liveMessage, authoritative.liveMessage) ||
    stream.draftText !== authoritative.draftText ||
    !areSamePendingRequests(pendingRequests, authoritative.pendingRequests) ||
    !areSameActivityItems(stream.activityItems, authoritative.activityItems)
  );
}
