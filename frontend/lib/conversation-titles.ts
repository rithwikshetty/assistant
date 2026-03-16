const DEFAULT_CONVERSATION_TITLE = "New Chat";
const PREVIEW_MAX_CHARS = 120;

const collapseWhitespace = (value: string): string => value.replace(/\s+/g, " ").trim();

export const isDefaultConversationTitle = (value?: string | null): boolean => {
  if (typeof value !== "string") return true;
  return collapseWhitespace(value).toLowerCase() === DEFAULT_CONVERSATION_TITLE.toLowerCase();
};

export const toConversationPreviewText = (
  value: string,
  maxChars: number = PREVIEW_MAX_CHARS,
): string | undefined => {
  const normalized = collapseWhitespace(value);
  if (!normalized) return undefined;
  if (normalized.length <= maxChars) return normalized;
  return `${normalized.slice(0, maxChars - 3).trimEnd()}...`;
};

export const resolveConversationDisplayTitle = (conversation: {
  title?: string | null;
  last_message_preview?: string | null;
}): string => {
  const title = (conversation.title ?? "").trim();
  const preview = (conversation.last_message_preview ?? "").trim();

  if (!title && preview) return preview;
  if (isDefaultConversationTitle(title) && preview) return preview;
  return title || DEFAULT_CONVERSATION_TITLE;
};

export { DEFAULT_CONVERSATION_TITLE };
