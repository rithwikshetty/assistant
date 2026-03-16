
/**
 * Messages cache bridge for the central chat runtime store.
 *
 * Active conversation transcript state now lives in the runtime store.
 * This module provides a non-hook read path for utilities that still need
 * message access outside React components.
 */

import { getActiveChatRuntimeStore } from "@/contexts/active-streams-context";
import { getQueryClient } from "@/lib/query/query-client";
import { queryKeys } from "@/lib/query/query-keys";

// Types for cached messages
export type MessageStatus =
  | { type: "running" }
  | { type: "requires-action"; reason: string }
  | { type: "complete"; reason?: string }
  | { type: "incomplete"; reason?: string };

export type AttachmentStatus =
  | { type: "running"; reason?: string; progress?: number }
  | { type: "requires-action"; reason?: string }
  | { type: "complete" }
  | { type: "incomplete"; reason?: string };

export type CompleteAttachment = {
  id: string;
  type: "file" | "image" | "document";
  name: string;
  contentType?: string;
  status: AttachmentStatus;
  content?: unknown[];
  meta?: Record<string, unknown>;
};

export type CachedMessage = {
  id?: string;
  role: "user" | "assistant";
  createdAt?: Date;
  content: unknown[];
  metadata?: Record<string, unknown>;
  attachments?: CompleteAttachment[];
  status?: MessageStatus;
};

/**
 * Get messages from the runtime store for a conversation.
 * Returns null if the conversation transcript has not been initialized.
 */
export function getMessagesFromCache(conversationId: string): CachedMessage[] | null {
  try {
    const runtimeStore = getActiveChatRuntimeStore();
    if (!runtimeStore) {
      return null;
    }
    const record = runtimeStore.getConversation(conversationId);
    if (!record.transcript.initialized) {
      return null;
    }
    return record.transcript.messages as CachedMessage[];
  } catch {
    return null;
  }
}

/**
 * Clear all message caches. Called on logout for privacy.
 */
export function clearAllMessageCaches() {
  try {
    getActiveChatRuntimeStore()?.resetAll();
  } catch {
    // Ignore runtime-store reset errors during cache clear
  }
  try {
    const queryClient = getQueryClient();
    queryClient.removeQueries({ queryKey: queryKeys.messages.all });
    queryClient.removeQueries({ queryKey: queryKeys.conversations.all });
  } catch {
    // Ignore errors during cache clear
  }
}
