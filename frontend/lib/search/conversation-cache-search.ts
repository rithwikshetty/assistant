import { getMessagesFromCache, type CachedMessage } from "@/lib/cache/messages-cache";

type SearchableConversation = {
  id: string;
  title: string;
  last_message_preview?: string | null;
};

type CacheEntry = {
  messagesRef: CachedMessage[];
  textLower: string;
};

const SEARCH_CACHE = new Map<string, CacheEntry>();

function appendScalarText(parts: string[], value: unknown): void {
  if (typeof value === "string") {
    const normalized = value.trim();
    if (normalized) {
      parts.push(normalized);
    }
    return;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    parts.push(String(value));
  }
}

function appendStructuredText(parts: string[], value: unknown, depth: number = 0): void {
  if (depth > 4 || value == null) return;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    appendScalarText(parts, value);
    return;
  }
  if (Array.isArray(value)) {
    for (const entry of value) {
      appendStructuredText(parts, entry, depth + 1);
    }
    return;
  }
  if (typeof value !== "object") {
    return;
  }

  for (const entry of Object.values(value as Record<string, unknown>)) {
    appendStructuredText(parts, entry, depth + 1);
  }
}

function extractSearchableText(messages: CachedMessage[]): string {
  const textParts: string[] = [];

  for (const msg of messages) {
    if (!Array.isArray(msg.content)) continue;

    for (const part of msg.content) {
      if (typeof part !== "object" || !part) continue;
      const typedPart = part as {
        type?: string;
        text?: string;
        toolName?: string;
        args?: Record<string, unknown>;
        result?: unknown;
      };

      if (typedPart.type === "text" && typedPart.text) {
        textParts.push(typedPart.text);
      } else if (typedPart.type === "reasoning" && typedPart.text) {
        textParts.push(typedPart.text);
      } else if (typedPart.type === "tool-call") {
        appendScalarText(textParts, typedPart.toolName);
        appendStructuredText(textParts, typedPart.args);
        appendStructuredText(textParts, typedPart.result);
      }
    }
  }

  return textParts.join(" ");
}

function getCachedSearchTextLower(conversationId: string): string {
  const messages = getMessagesFromCache(conversationId);
  if (!messages || messages.length === 0) {
    SEARCH_CACHE.delete(conversationId);
    return "";
  }

  const cached = SEARCH_CACHE.get(conversationId);
  if (cached && cached.messagesRef === messages) {
    return cached.textLower;
  }

  const textLower = extractSearchableText(messages).toLowerCase();
  SEARCH_CACHE.set(conversationId, { messagesRef: messages, textLower });
  return textLower;
}

export function conversationMatchesQuery(
  conversation: SearchableConversation,
  queryLower: string,
): boolean {
  if (!queryLower) return true;
  if (conversation.title.toLowerCase().includes(queryLower)) return true;
  if (conversation.last_message_preview?.toLowerCase().includes(queryLower)) return true;
  return getCachedSearchTextLower(conversation.id).includes(queryLower);
}

export function clearConversationSearchCache(): void {
  SEARCH_CACHE.clear();
}
