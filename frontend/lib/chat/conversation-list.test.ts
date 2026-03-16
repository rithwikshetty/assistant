import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { ConversationSummary } from "@/lib/api/auth";
import { queryKeys } from "@/lib/query/query-keys";
import {
  applyConversationRuntimePatch,
  applyConversationTitlePatch,
  mergeConversationSummary,
  patchConversationRuntimeInCaches,
  patchConversationTitleInCaches,
  reconcileConversationSummaries,
  upsertConversationSummary,
} from "@/lib/chat/conversation-list";

function buildConversationSummary(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    id: "conv_1",
    title: "New Chat",
    updated_at: "2026-03-11T00:00:00Z",
    last_message_at: "2026-03-11T00:00:00Z",
    message_count: 1,
    last_message_preview: "Original preview",
    project_id: null,
    parent_conversation_id: null,
    archived: false,
    archived_at: null,
    archived_by: null,
    owner_id: "user_1",
    owner_name: "Test User",
    owner_email: "test@example.com",
    is_owner: true,
    can_edit: true,
    ...overrides,
  };
}

describe("conversation list title patches", () => {
  it("updates the title of an existing conversation summary", () => {
    const current = [buildConversationSummary()];

    const next = applyConversationTitlePatch(current, {
      conversationId: "conv_1",
      title: "Analysing project data",
      updatedAt: "2026-03-11T01:02:03Z",
    });

    expect(next).toEqual([
      expect.objectContaining({
        id: "conv_1",
        title: "Analysing project data",
        updated_at: "2026-03-11T01:02:03Z",
      }),
    ]);
  });

  it("preserves an existing generated title when a later summary still has the default title", () => {
    const existing = buildConversationSummary({
      title: "Analyse project costs",
      updated_at: "2026-03-11T02:03:04Z",
      last_message_preview: "Generated preview",
    });
    const incoming = buildConversationSummary({
      title: "New Chat",
      updated_at: "2026-03-11T02:00:00Z",
      last_message_preview: "Real preview from server",
    });

    expect(mergeConversationSummary(existing, incoming)).toEqual(
      expect.objectContaining({
        id: "conv_1",
        title: "Analyse project costs",
        updated_at: "2026-03-11T02:03:04Z",
        last_message_preview: "Real preview from server",
      }),
    );
  });

  it("accepts a newer default title when the server row is actually newer", () => {
    const existing = buildConversationSummary({
      title: "Analyse project costs",
      updated_at: "2026-03-11T02:03:04Z",
    });
    const incoming = buildConversationSummary({
      title: "New Chat",
      updated_at: "2026-03-11T02:05:00Z",
    });

    expect(mergeConversationSummary(existing, incoming)).toEqual(
      expect.objectContaining({
        id: "conv_1",
        title: "New Chat",
        updated_at: "2026-03-11T02:05:00Z",
      }),
    );
  });

  it("inserts a placeholder summary when the title arrives before the list row exists", () => {
    const next = applyConversationTitlePatch([], {
      conversationId: "conv_2",
      title: "Generated title",
      updatedAt: "2026-03-11T01:02:03Z",
    });

    expect(next).toEqual([
      expect.objectContaining({
        id: "conv_2",
        title: "Generated title",
        updated_at: "2026-03-11T01:02:03Z",
        last_message_at: "2026-03-11T01:02:03Z",
      }),
    ]);
  });

  it("preserves a generated title when a later upsert still carries the default title", () => {
    const existing = buildConversationSummary({
      title: "Analyse project costs",
      updated_at: "2026-03-11T02:03:04Z",
    });
    const incoming = buildConversationSummary({
      title: "New Chat",
      updated_at: "2026-03-11T02:00:00Z",
      last_message_preview: "Fresh preview",
    });

    const result = upsertConversationSummary([existing], incoming);

    expect(result.existed).toBe(true);
    expect(result.next).toEqual([
      expect.objectContaining({
        id: "conv_1",
        title: "Analyse project costs",
        updated_at: "2026-03-11T02:03:04Z",
        last_message_preview: "Fresh preview",
      }),
    ]);
  });

  it("preserves cached generated titles across stale list refetches", () => {
    const existing = [
      buildConversationSummary({
        id: "conv_1",
        title: "Analyse project costs",
        updated_at: "2026-03-11T02:03:04Z",
      }),
    ];
    const incoming = [
      buildConversationSummary({
        id: "conv_1",
        title: "New Chat",
        updated_at: "2026-03-11T02:00:00Z",
      }),
    ];

    expect(reconcileConversationSummaries(existing, incoming)).toEqual([
      expect.objectContaining({
        id: "conv_1",
        title: "Analyse project costs",
        updated_at: "2026-03-11T02:03:04Z",
      }),
    ]);
  });

  it("patches every conversations cache via QueryClient", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.conversations.list("user_1"), [buildConversationSummary()]);

    patchConversationTitleInCaches(queryClient, {
      conversationId: "conv_1",
      title: "Updated from cache helper",
      updatedAt: "2026-03-11T02:03:04Z",
    });

    expect(
      queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations.list("user_1")),
    ).toEqual([
      expect.objectContaining({
        id: "conv_1",
        title: "Updated from cache helper",
        updated_at: "2026-03-11T02:03:04Z",
      }),
    ]);
  });

  it("moves an active non-pinned conversation below pinned rows when local activity updates recency", () => {
    const current = [
      buildConversationSummary({
        id: "conv_pinned",
        title: "Pinned",
        is_pinned: true,
        pinned_at: "2026-03-11T00:00:00Z",
      }),
      buildConversationSummary({
        id: "conv_old",
        title: "Older",
        updated_at: "2026-03-10T00:00:00Z",
        last_message_at: "2026-03-10T00:00:00Z",
      }),
      buildConversationSummary({
        id: "conv_live",
        title: "Live",
        updated_at: "2026-03-09T00:00:00Z",
        last_message_at: "2026-03-09T00:00:00Z",
      }),
    ];

    const next = applyConversationRuntimePatch(current, {
      conversationId: "conv_live",
      updatedAt: "2026-03-12T02:03:04Z",
      lastMessageAt: "2026-03-12T02:03:04Z",
      lastMessagePreview: "Newest local preview",
      messageCountDelta: 1,
      awaitingUserInput: false,
    });

    expect(next.map((conversation) => conversation.id)).toEqual([
      "conv_pinned",
      "conv_live",
      "conv_old",
    ]);
    expect(next[1]).toEqual(
      expect.objectContaining({
        id: "conv_live",
        message_count: 2,
        last_message_preview: "Newest local preview",
        awaiting_user_input: false,
      }),
    );
  });

  it("preserves pinned ordering by pinned_at when a pinned conversation gets new activity", () => {
    const current = [
      buildConversationSummary({
        id: "conv_recent_pin",
        title: "Recent pin",
        is_pinned: true,
        pinned_at: "2026-03-12T00:00:00Z",
        updated_at: "2026-03-12T00:00:00Z",
        last_message_at: "2026-03-12T00:00:00Z",
      }),
      buildConversationSummary({
        id: "conv_old_pin",
        title: "Older pin",
        is_pinned: true,
        pinned_at: "2026-03-10T00:00:00Z",
        updated_at: "2026-03-10T00:00:00Z",
        last_message_at: "2026-03-10T00:00:00Z",
      }),
      buildConversationSummary({
        id: "conv_unpinned",
        title: "Unpinned",
        updated_at: "2026-03-09T00:00:00Z",
        last_message_at: "2026-03-09T00:00:00Z",
      }),
    ];

    const next = applyConversationRuntimePatch(current, {
      conversationId: "conv_old_pin",
      updatedAt: "2026-03-13T02:03:04Z",
      lastMessageAt: "2026-03-13T02:03:04Z",
      lastMessagePreview: "Pinned activity",
      messageCountDelta: 1,
    });

    expect(next.map((conversation) => conversation.id)).toEqual([
      "conv_recent_pin",
      "conv_old_pin",
      "conv_unpinned",
    ]);
  });

  it("patches waiting-for-input state across conversations caches", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.conversations.list("user_1"), [buildConversationSummary()]);

    patchConversationRuntimeInCaches(queryClient, {
      conversationId: "conv_1",
      awaitingUserInput: true,
    });

    expect(
      queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations.list("user_1")),
    ).toEqual([
      expect.objectContaining({
        id: "conv_1",
        awaiting_user_input: true,
      }),
    ]);
  });
});
