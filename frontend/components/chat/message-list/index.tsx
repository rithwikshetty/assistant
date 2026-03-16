
/**
 * MessageList - Backend-Driven Message Rendering
 *
 * This component renders messages directly from backend data.
 *
 * Features:
 * - Renders user and assistant messages
 * - Supports tool calls, reasoning blocks, and text content
 * - Renders content in-order (text + tools + reasoning)
 * - Visible tools (charts, tasks, etc.) render directly
 * - Works with the useChat hook
 */

import { memo, type FC, useEffect, useMemo } from "react";
import { type VirtualItem, useVirtualizer } from "@tanstack/react-virtual";
import { cn } from "@/lib/utils";
import type { MessageListProps } from "./types";
import { UserMessageHeader } from "./user-message-header";
import { AssistantMessageItem } from "./assistant-message-item";

// ============================================================================
// MessageList Component
// ============================================================================

type TranscriptRowsProps = Pick<
  MessageListProps,
  "messages" | "conversationId" | "viewerIsOwner" | "canGiveFeedback" | "getScrollElement"
>;

const MIN_VIRTUALIZED_MESSAGE_COUNT = 40;
const ALWAYS_UNVIRTUALIZED_TAIL_MESSAGES = 8;
const VIRTUAL_OVERSCAN = 6;

function estimateMessageHeight(message: MessageListProps["messages"][number]): number {
  let textLength = 0;
  let structuredPartCount = 0;
  for (const part of message.content) {
    if (part.type === "text" || part.type === "reasoning") {
      textLength += typeof part.text === "string" ? part.text.length : 0;
    } else {
      structuredPartCount += 1;
    }
  }
  const attachmentCount = message.attachments?.length ?? 0;
  const baseHeight = message.role === "user" ? 96 : 168;
  const textHeight = Math.ceil(textLength / 72) * 22;
  const attachmentHeight = attachmentCount * 168;
  const structuredHeight = structuredPartCount * 108;
  return Math.min(1600, baseHeight + textHeight + attachmentHeight + structuredHeight + 12);
}

function MessageRow(props: {
  message: MessageListProps["messages"][number];
  index: number;
  total: number;
  conversationId?: string;
  viewerIsOwner?: boolean;
  canGiveFeedback?: boolean;
}) {
  const { message, index, total, conversationId, viewerIsOwner = true, canGiveFeedback = true } = props;

  return (
    <div
      data-message-id={message.id}
      className="w-full min-w-0 max-w-[var(--thread-max-width,48rem)] pb-3"
    >
      {message.role === "user" ? (
        <UserMessageHeader message={message} />
      ) : (
        <AssistantMessageItem
          message={message}
          conversationId={conversationId}
          viewerIsOwner={viewerIsOwner}
          canGiveFeedback={canGiveFeedback}
          isLast={index === total - 1}
        />
      )}
    </div>
  );
}

const TranscriptRows = memo<TranscriptRowsProps>(function TranscriptRows({
  messages,
  conversationId,
  viewerIsOwner = true,
  canGiveFeedback = true,
  getScrollElement,
}) {
  const shouldVirtualize = messages.length >= MIN_VIRTUALIZED_MESSAGE_COUNT;
  const firstNonVirtualizedIndex = useMemo(() => {
    if (!shouldVirtualize) return 0;
    return Math.max(messages.length - ALWAYS_UNVIRTUALIZED_TAIL_MESSAGES, 0);
  }, [messages.length, shouldVirtualize]);
  const virtualizedMessages = useMemo(
    () => (shouldVirtualize ? messages.slice(0, firstNonVirtualizedIndex) : messages),
    [firstNonVirtualizedIndex, messages, shouldVirtualize],
  );
  const nonVirtualizedTail = useMemo(
    () => (shouldVirtualize ? messages.slice(firstNonVirtualizedIndex) : []),
    [firstNonVirtualizedIndex, messages, shouldVirtualize],
  );

  const rowVirtualizer = useVirtualizer({
    count: virtualizedMessages.length,
    getScrollElement: () => getScrollElement?.() ?? null,
    getItemKey: (index) => virtualizedMessages[index]?.id ?? index,
    estimateSize: (index) => estimateMessageHeight(virtualizedMessages[index]),
    overscan: VIRTUAL_OVERSCAN,
  });

  useEffect(() => {
    rowVirtualizer.measure();
  }, [messages.length, rowVirtualizer]);

  if (!shouldVirtualize) {
    return (
      <>
        {messages.map((message, index) => (
          <MessageRow
            key={message.id}
            message={message}
            index={index}
            total={messages.length}
            conversationId={conversationId}
            viewerIsOwner={viewerIsOwner}
            canGiveFeedback={canGiveFeedback}
          />
        ))}
      </>
    );
  }

  const virtualRows = rowVirtualizer.getVirtualItems();

  return (
    <>
      {virtualizedMessages.length > 0 && (
        <div className="relative" style={{ height: `${rowVirtualizer.getTotalSize()}px` }}>
          {virtualRows.map((virtualRow: VirtualItem) => {
            const message = virtualizedMessages[virtualRow.index];
            if (!message) return null;
            return (
              <div
                key={`virtual-row:${message.id}`}
                data-index={virtualRow.index}
                ref={rowVirtualizer.measureElement}
                className="absolute left-0 top-0 w-full"
                style={{ transform: `translateY(${virtualRow.start}px)` }}
              >
                <MessageRow
                  message={message}
                  index={virtualRow.index}
                  total={messages.length}
                  conversationId={conversationId}
                  viewerIsOwner={viewerIsOwner}
                  canGiveFeedback={canGiveFeedback}
                />
              </div>
            );
          })}
        </div>
      )}

      {nonVirtualizedTail.map((message, index) => (
        <MessageRow
          key={`tail-row:${message.id}`}
          message={message}
          index={firstNonVirtualizedIndex + index}
          total={messages.length}
          conversationId={conversationId}
          viewerIsOwner={viewerIsOwner}
          canGiveFeedback={canGiveFeedback}
        />
      ))}
    </>
  );
});

TranscriptRows.displayName = "TranscriptRows";

export const MessageList: FC<MessageListProps> = ({
  messages,
  conversationId,
  viewerIsOwner = true,
  canGiveFeedback = true,
  getScrollElement,
  className,
}) => {
  if (messages.length === 0) {
    return null;
  }

  return (
    <div className={cn("pt-3 pb-0", className)}>
      <TranscriptRows
        messages={messages}
        conversationId={conversationId}
        viewerIsOwner={viewerIsOwner}
        canGiveFeedback={canGiveFeedback}
        getScrollElement={getScrollElement}
      />
    </div>
  );
};

// Re-export types and components for convenience
export type { MessageListProps, Message, MessageContentPart } from "./types";
export { AssistantMessageContent } from "./assistant-message-content";
export { AssistantActionBar } from "./assistant-action-bar";
export { UserMessageHeader } from "./user-message-header";
export { AssistantMessageItem } from "./assistant-message-item";
export { TextPart, ReasoningPart, ToolCallPart, ContentPart } from "./content-parts";
export * from "./tool-results";
export {
  getToolIcon,
  getToolDisplayName,
  formatDuration,
  formatWorkedDuration,
  segmentContent,
} from "./utils";
