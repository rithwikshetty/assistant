import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CachedMessage } from "@/lib/cache/messages-cache";
import { getMessagesFromCache } from "@/lib/cache/messages-cache";
import {
  clearConversationSearchCache,
  conversationMatchesQuery,
} from "./conversation-cache-search";

vi.mock("@/lib/cache/messages-cache", () => ({
  getMessagesFromCache: vi.fn(),
}));

const getMessagesFromCacheMock = vi.mocked(getMessagesFromCache);

const conversation = {
  id: "conv_1",
  title: "Project kickoff",
  last_message_preview: "Latest draft ready",
};

describe("conversation cache search", () => {
  beforeEach(() => {
    clearConversationSearchCache();
    getMessagesFromCacheMock.mockReset();
  });

  it("short-circuits when query is empty", () => {
    const result = conversationMatchesQuery(conversation, "");
    expect(result).toBe(true);
    expect(getMessagesFromCacheMock).not.toHaveBeenCalled();
  });

  it("matches against title and preview before cache lookup", () => {
    expect(conversationMatchesQuery(conversation, "kickoff")).toBe(true);
    expect(conversationMatchesQuery(conversation, "latest draft")).toBe(true);
    expect(getMessagesFromCacheMock).not.toHaveBeenCalled();
  });

  it("matches cached message text/reasoning/tool-call args", () => {
    const messages: CachedMessage[] = [
      {
        role: "assistant",
        content: [
          { type: "reasoning", text: "Need to validate quantities" },
          {
            type: "tool-call",
            toolCallId: "call_1",
            toolName: "retrieval_project_files",
            args: { query: "floor area schedule" },
            result: { message: "Matched basement ventilation schedule" },
          },
          { type: "text", text: "Use Spon's 2024 rates for baseline." },
        ],
      },
    ];
    getMessagesFromCacheMock.mockReturnValue(messages);

    expect(conversationMatchesQuery({ ...conversation, title: "x", last_message_preview: null }, "floor area")).toBe(true);
    expect(conversationMatchesQuery({ ...conversation, title: "x", last_message_preview: null }, "basement ventilation")).toBe(true);
    expect(conversationMatchesQuery({ ...conversation, title: "x", last_message_preview: null }, "spon's 2024")).toBe(true);
    expect(conversationMatchesQuery({ ...conversation, title: "x", last_message_preview: null }, "validate quantities")).toBe(true);
    expect(conversationMatchesQuery({ ...conversation, title: "x", last_message_preview: null }, "not present")).toBe(false);
  });

  it("rebuilds cache when messages array reference changes", () => {
    const initialMessages: CachedMessage[] = [
      { role: "assistant", content: [{ type: "text", text: "alpha rates" }] },
    ];
    const refreshedMessages: CachedMessage[] = [
      { role: "assistant", content: [{ type: "text", text: "beta rates" }] },
    ];
    getMessagesFromCacheMock
      .mockReturnValueOnce(initialMessages)
      .mockReturnValueOnce(refreshedMessages);

    const baseConversation = { ...conversation, title: "x", last_message_preview: null };
    expect(conversationMatchesQuery(baseConversation, "beta")).toBe(false);
    expect(conversationMatchesQuery(baseConversation, "beta")).toBe(true);
  });
});
