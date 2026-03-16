import type { QueryClient } from "@tanstack/react-query";

import type { ConversationSummary } from "@/lib/api/auth";
import { isDefaultConversationTitle } from "@/lib/conversation-titles";
import { queryKeys } from "@/lib/query/query-keys";

export type ConversationUpsertResult = {
  next: ConversationSummary[];
  existed: boolean;
};

type ConversationRuntimePatch = {
  conversationId: string;
  updatedAt?: string | null;
  lastMessageAt?: string | null;
  lastMessagePreview?: string | null;
  messageCountDelta?: number;
  awaitingUserInput?: boolean;
};

function compareIsoTimestampDesc(
  left: string | null | undefined,
  right: string | null | undefined,
): number {
  const normalizedLeft = typeof left === "string" ? left.trim() : "";
  const normalizedRight = typeof right === "string" ? right.trim() : "";
  if (normalizedLeft === normalizedRight) {
    return 0;
  }
  return normalizedLeft > normalizedRight ? -1 : 1;
}

export function compareConversationSummariesForList(
  left: ConversationSummary,
  right: ConversationSummary,
): number {
  const leftPinned = Boolean(left.is_pinned);
  const rightPinned = Boolean(right.is_pinned);
  if (leftPinned !== rightPinned) {
    return leftPinned ? -1 : 1;
  }

  if (leftPinned && rightPinned) {
    const pinnedAtComparison = compareIsoTimestampDesc(left.pinned_at, right.pinned_at);
    if (pinnedAtComparison !== 0) {
      return pinnedAtComparison;
    }
  }

  const lastMessageComparison = compareIsoTimestampDesc(left.last_message_at, right.last_message_at);
  if (lastMessageComparison !== 0) {
    return lastMessageComparison;
  }

  const updatedAtComparison = compareIsoTimestampDesc(left.updated_at, right.updated_at);
  if (updatedAtComparison !== 0) {
    return updatedAtComparison;
  }

  return left.id.localeCompare(right.id);
}

export function upsertConversationSummary(
  current: ConversationSummary[],
  summary: ConversationSummary,
): ConversationUpsertResult {
  let existed = false;
  const filtered = current.filter((item) => {
    if (item.id !== summary.id) return true;
    existed = true;
    return false;
  });

  const existing = current.find((item) => item.id === summary.id) ?? null;
  const nextSummary = existing
    ? mergeConversationSummary(existing, summary)
    : summary;

  return {
    next: [nextSummary, ...filtered],
    existed,
  };
}

function insertConversationForRecency(
  current: ConversationSummary[],
  conversation: ConversationSummary,
): ConversationSummary[] {
  const insertIndex = current.findIndex((item) => compareConversationSummariesForList(conversation, item) < 0);
  const next = current.slice();
  next.splice(insertIndex === -1 ? next.length : insertIndex, 0, conversation);
  return next;
}

type ConversationTitlePatch = {
  conversationId: string;
  title: string | null;
  updatedAt?: string | null;
};

export function applyConversationTitlePatch(
  current: ConversationSummary[],
  patch: ConversationTitlePatch,
): ConversationSummary[] {
  const conversationId = patch.conversationId.trim();
  if (!conversationId) {
    return current;
  }

  const title = typeof patch.title === "string" ? patch.title.trim() : "";
  const updatedAt =
    typeof patch.updatedAt === "string" && patch.updatedAt.trim().length > 0
      ? patch.updatedAt
      : new Date().toISOString();

  let found = false;
  const next = current.map((conversation) => {
    if (conversation.id !== conversationId) {
      return conversation;
    }
    found = true;
    return {
      ...conversation,
      title: title || conversation.title,
      updated_at: updatedAt,
    };
  });

  if (found || !title) {
    return next;
  }

  const placeholder: ConversationSummary = {
    id: conversationId,
    title,
    updated_at: updatedAt,
    last_message_at: updatedAt,
    message_count: 1,
    last_message_preview: undefined,
    project_id: null,
    parent_conversation_id: undefined,
    archived: false,
    archived_at: null,
    archived_by: null,
    owner_id: "",
    owner_name: null,
    owner_email: null,
    is_owner: true,
    can_edit: true,
  };

  return [placeholder, ...next];
}

function resolvePreferredTitle(
  existingTitle: string | null | undefined,
  incomingTitle: string | null | undefined,
  existingUpdatedAt: string | null | undefined,
  incomingUpdatedAt: string | null | undefined,
): string {
  const normalizedExisting = typeof existingTitle === "string" ? existingTitle.trim() : "";
  const normalizedIncoming = typeof incomingTitle === "string" ? incomingTitle.trim() : "";
  const normalizedExistingUpdatedAt = typeof existingUpdatedAt === "string" ? existingUpdatedAt.trim() : "";
  const normalizedIncomingUpdatedAt = typeof incomingUpdatedAt === "string" ? incomingUpdatedAt.trim() : "";

  if (!normalizedIncoming && normalizedExisting) {
    return existingTitle ?? normalizedExisting;
  }
  if (
    normalizedExisting &&
    !isDefaultConversationTitle(normalizedExisting) &&
    isDefaultConversationTitle(normalizedIncoming) &&
    (!normalizedIncomingUpdatedAt || normalizedIncomingUpdatedAt <= normalizedExistingUpdatedAt)
  ) {
    return existingTitle ?? normalizedExisting;
  }
  return incomingTitle ?? normalizedIncoming;
}

function resolvePreferredUpdatedAt(
  existingUpdatedAt: string | null | undefined,
  incomingUpdatedAt: string | null | undefined,
): string {
  const normalizedExisting = typeof existingUpdatedAt === "string" ? existingUpdatedAt.trim() : "";
  const normalizedIncoming = typeof incomingUpdatedAt === "string" ? incomingUpdatedAt.trim() : "";

  if (!normalizedExisting) return normalizedIncoming;
  if (!normalizedIncoming) return normalizedExisting;
  return normalizedExisting > normalizedIncoming ? normalizedExisting : normalizedIncoming;
}

export function mergeConversationSummary(
  existing: ConversationSummary,
  incoming: ConversationSummary,
): ConversationSummary {
  return {
    ...existing,
    ...incoming,
    title: resolvePreferredTitle(
      existing.title,
      incoming.title,
      existing.updated_at,
      incoming.updated_at,
    ),
    updated_at: resolvePreferredUpdatedAt(existing.updated_at, incoming.updated_at),
    last_message_at: incoming.last_message_at || existing.last_message_at,
    last_message_preview: incoming.last_message_preview ?? existing.last_message_preview,
  };
}

export function applyConversationRuntimePatch(
  current: ConversationSummary[],
  patch: ConversationRuntimePatch,
): ConversationSummary[] {
  const conversationId = patch.conversationId.trim();
  if (!conversationId) {
    return current;
  }

  const existingIndex = current.findIndex((conversation) => conversation.id === conversationId);
  if (existingIndex === -1) {
    return current;
  }

  const existing = current[existingIndex];
  const updatedAt =
    typeof patch.updatedAt === "string" && patch.updatedAt.trim().length > 0
      ? patch.updatedAt
      : existing.updated_at;
  const lastMessageAt =
    typeof patch.lastMessageAt === "string" && patch.lastMessageAt.trim().length > 0
      ? patch.lastMessageAt
      : existing.last_message_at;
  const nextMessageCount = typeof patch.messageCountDelta === "number" && Number.isFinite(patch.messageCountDelta)
    ? Math.max(0, existing.message_count + Math.trunc(patch.messageCountDelta))
    : existing.message_count;

  const nextConversation: ConversationSummary = {
    ...existing,
    updated_at: updatedAt,
    last_message_at: lastMessageAt,
    message_count: nextMessageCount,
    last_message_preview:
      patch.lastMessagePreview !== undefined
        ? patch.lastMessagePreview
        : existing.last_message_preview,
    awaiting_user_input:
      typeof patch.awaitingUserInput === "boolean"
        ? patch.awaitingUserInput
        : existing.awaiting_user_input,
  };

  const withoutExisting = current.filter((conversation) => conversation.id !== conversationId);
  const recencyChanged = updatedAt !== existing.updated_at || lastMessageAt !== existing.last_message_at;
  if (!recencyChanged) {
    return insertConversationAtExistingIndex(withoutExisting, nextConversation, existingIndex);
  }
  return insertConversationForRecency(withoutExisting, nextConversation);
}

function insertConversationAtExistingIndex(
  current: ConversationSummary[],
  conversation: ConversationSummary,
  index: number,
): ConversationSummary[] {
  const next = current.slice();
  const boundedIndex = Math.max(0, Math.min(index, next.length));
  next.splice(boundedIndex, 0, conversation);
  return next;
}

export function reconcileConversationSummaries(
  existing: ConversationSummary[],
  incoming: ConversationSummary[],
): ConversationSummary[] {
  if (existing.length === 0 || incoming.length === 0) {
    return incoming;
  }

  const existingById = new Map(existing.map((conversation) => [conversation.id, conversation]));
  return incoming.map((conversation) => {
    const previous = existingById.get(conversation.id);
    return previous ? mergeConversationSummary(previous, conversation) : conversation;
  });
}

export function patchConversationTitleInCaches(
  queryClient: QueryClient,
  patch: ConversationTitlePatch,
): void {
  queryClient.setQueriesData<ConversationSummary[]>(
    { queryKey: queryKeys.conversations.all },
    (current) => applyConversationTitlePatch(current ?? [], patch),
  );
}

export function patchConversationRuntimeInCaches(
  queryClient: QueryClient,
  patch: ConversationRuntimePatch,
): void {
  queryClient.setQueriesData<ConversationSummary[]>(
    { queryKey: queryKeys.conversations.all },
    (current) => applyConversationRuntimePatch(current ?? [], patch),
  );
}
