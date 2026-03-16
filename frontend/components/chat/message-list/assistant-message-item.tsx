
/**
 * AssistantMessageItem - Renders a complete assistant message
 */

import { memo, type FC } from "react";
import { cn } from "@/lib/utils";
import type { Message } from "./types";
import { AssistantMessageContent } from "./assistant-message-content";
import { AssistantActionBar } from "./assistant-action-bar";

// ============================================================================
// AssistantMessageItem Component
// ============================================================================

type AssistantMessageItemProps = {
  message: Message;
  conversationId?: string;
  viewerIsOwner?: boolean;
  canGiveFeedback?: boolean;
  isLast?: boolean;
};

const AssistantMessageItemComponent: FC<AssistantMessageItemProps> = ({
  message,
  conversationId,
  viewerIsOwner = true,
  canGiveFeedback = true,
  isLast = false,
}) => {
  const streamingStatus = message.streamingStatus ?? null;
  const hasContent = message.content.length > 0;
  const isWaitingForInput =
    message.status === "awaiting_input" || streamingStatus?.phase === "awaiting_input";

  return (
    <div className="group grid grid-cols-[auto_auto_1fr] grid-rows-[auto_1fr] relative w-full min-w-0 max-w-[var(--thread-max-width,48rem)] py-1">
      <div
        className="text-foreground w-full min-w-0 break-words leading-7 col-span-2 col-start-2 row-start-1 my-1"
        data-message-content="true"
      >
        <AssistantMessageContent
          content={message.content}
          messageId={message.id}
          conversationId={conversationId}
          isLast={isLast}
          messageStatus={message.status}
          responseLatencyMs={message.responseLatencyMs}
        />
        {streamingStatus?.label && (
          <div
            className={cn(
              "text-muted-foreground/70 tool-connectable leading-normal",
              hasContent ? "type-size-12 mt-2" : "type-size-14",
            )}
          >
            <span
              className={cn(
                "font-medium truncate max-w-[540px] inline-block",
                hasContent && "tracking-wide",
                !isWaitingForInput && "shimmer-text shimmer-slow",
              )}
            >
              {streamingStatus.label}
            </span>
          </div>
        )}
      </div>

      <AssistantActionBar
        message={message}
        conversationId={conversationId}
        viewerIsOwner={viewerIsOwner}
        canGiveFeedback={canGiveFeedback}
        isLast={isLast}
        isStreaming={Boolean(streamingStatus)}
      />
    </div>
  );
};

export const AssistantMessageItem = memo(AssistantMessageItemComponent);
AssistantMessageItem.displayName = "AssistantMessageItem";
