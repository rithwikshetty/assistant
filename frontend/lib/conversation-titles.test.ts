import { describe, expect, it } from "vitest";

import {
  DEFAULT_CONVERSATION_TITLE,
  isDefaultConversationTitle,
  resolveConversationDisplayTitle,
  toConversationPreviewText,
} from "./conversation-titles";

describe("conversation-titles", () => {
  it("treats New Chat as the default title", () => {
    expect(isDefaultConversationTitle("New Chat")).toBe(true);
    expect(isDefaultConversationTitle(" new   chat ")).toBe(true);
    expect(isDefaultConversationTitle("Estimate update")).toBe(false);
  });

  it("builds a sanitized preview with max length", () => {
    expect(toConversationPreviewText("  Line one\nline two  ")).toBe("Line one line two");
    expect(toConversationPreviewText("")).toBeUndefined();

    const longText = "a".repeat(140);
    const preview = toConversationPreviewText(longText, 20);
    expect(preview).toBe("aaaaaaaaaaaaaaaaa...");
  });

  it("prefers message preview while title is default", () => {
    expect(resolveConversationDisplayTitle({
      title: DEFAULT_CONVERSATION_TITLE,
      last_message_preview: "Can you draft a project update email?",
    })).toBe("Can you draft a project update email?");

    expect(resolveConversationDisplayTitle({
      title: "Project update draft",
      last_message_preview: "Can you draft a project update email?",
    })).toBe("Project update draft");
  });
});
