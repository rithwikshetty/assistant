import {
  type ChatConversationTitleUpdatedUserEvent,
  type ChatInitialStateUserEvent,
  type ChatRunLifecycleUserEvent,
  type ChatUserActiveStream,
  type ChatUserEvent,
  isChatUserEventType,
} from "@/lib/chat/generated/ws-contract";
import { isRecord } from "@/lib/contracts/contract-utils";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";

function parseNullableString(value: unknown): string | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return normalizeNonEmptyString(value);
}

function parseActiveStream(raw: unknown): ChatUserActiveStream | null {
  if (!isRecord(raw)) return null;
  const conversationId = normalizeNonEmptyString(raw.conversation_id);
  if (!conversationId) return null;
  return {
    conversation_id: conversationId,
    user_message_id: parseNullableString(raw.user_message_id),
    run_id: parseNullableString(raw.run_id),
    started_at: parseNullableString(raw.started_at),
    current_step: parseNullableString(raw.current_step),
  };
}

function parseInitialStateEvent(raw: Record<string, unknown>): ChatInitialStateUserEvent {
  const streamsRaw = Array.isArray(raw.streams) ? raw.streams : [];
  const streams = streamsRaw
    .map((entry) => parseActiveStream(entry))
    .filter((entry): entry is ChatUserActiveStream => entry !== null);
  return {
    type: "initial_state",
    streams,
  };
}

function parseRunLifecycleEvent(raw: Record<string, unknown>): ChatRunLifecycleUserEvent | null {
  if (
    raw.type !== "stream_started" &&
    raw.type !== "stream_resumed" &&
    raw.type !== "stream_paused" &&
    raw.type !== "stream_completed" &&
    raw.type !== "stream_failed"
  ) {
    return null;
  }
  const conversationId = normalizeNonEmptyString(raw.conversation_id);
  if (!conversationId) return null;
  return {
    type: raw.type,
    conversation_id: conversationId,
    user_message_id: parseNullableString(raw.user_message_id),
    run_id: parseNullableString(raw.run_id),
    status: parseNullableString(raw.status),
    current_step: parseNullableString(raw.current_step),
    started_at: parseNullableString(raw.started_at),
  };
}

function parseConversationTitleUpdatedEvent(
  raw: Record<string, unknown>,
): ChatConversationTitleUpdatedUserEvent | null {
  const conversationId = normalizeNonEmptyString(raw.conversation_id);
  const title = normalizeNonEmptyString(raw.title);
  if (!conversationId || !title) return null;
  return {
    type: "conversation_title_updated",
    conversation_id: conversationId,
    title,
    updated_at: parseNullableString(raw.updated_at),
    source: parseNullableString(raw.source),
  };
}

export function parseChatUserEvent(raw: unknown): ChatUserEvent | null {
  if (!isRecord(raw) || !isChatUserEventType(raw.type)) {
    return null;
  }

  if (raw.type === "initial_state") {
    return parseInitialStateEvent(raw);
  }

  if (raw.type === "conversation_title_updated") {
    return parseConversationTitleUpdatedEvent(raw);
  }

  return parseRunLifecycleEvent(raw);
}

export type { ChatUserActiveStream, ChatUserEvent, ChatRunLifecycleUserEvent };
