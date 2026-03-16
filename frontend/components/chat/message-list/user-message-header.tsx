
/**
 * UserMessageHeader - Renders user message with bubble style
 */

import { memo, useState, useCallback, type FC } from "react";
import * as Popover from "@radix-ui/react-popover";
import { FileText, Copy as CopyIcon, Check as CheckIcon } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import type { Message } from "./types";

// ============================================================================
// Mention parsing & rendering
// ============================================================================

/** Matches @Name <email> tokens produced by the backend */
const MENTION_RE = /@([^<\n]+?)\s*<([^>\s]+@[^>\s]+)>/g;

/** Splits plain text into text segments and inline MentionTag elements */
function parseMentions(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  MENTION_RE.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = MENTION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(
      <MentionTag key={`m-${match.index}`} name={match[1].trim()} email={match[2].trim()} />
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

/** Inline clickable mention that opens a small popover with the email */
const MentionTag: FC<{ name: string; email: string }> = ({ name, email }) => {
  const initials = name
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0])
    .join("")
    .toUpperCase();

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="inline text-primary/90 font-medium underline underline-offset-2 decoration-primary/30 cursor-pointer transition-colors hover:text-primary hover:decoration-primary/60"
        >
          @{name}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          sideOffset={6}
          className="z-50 rounded-xl border bg-popover px-3 py-2.5 text-popover-foreground shadow-lg animate-in fade-in-0 zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2"
        >
          <div className="flex items-center gap-2.5">
            <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 type-control-compact text-primary shrink-0">
              {initials}
            </span>
            <div className="min-w-0">
              <div className="type-control-compact truncate">{name}</div>
              <div className="type-nav-meta text-muted-foreground truncate">{email}</div>
            </div>
          </div>
          <Popover.Arrow className="fill-popover" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
};

// ============================================================================
// UserMessageHeader Component
// ============================================================================

type UserMessageHeaderProps = {
  message: Message;
};

const UserMessageHeaderComponent: FC<UserMessageHeaderProps> = ({ message }) => {
  const [copied, setCopied] = useState(false);

  const textContent = message.content
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n\n");

  const hasAttachments = message.attachments && message.attachments.length > 0;
  const trimmedText = textContent.trim();
  const hasText = trimmedText.length > 0;
  const isMultiLine = textContent.includes("\n");
  const isShortSingleLine = !hasAttachments && hasText && !isMultiLine && trimmedText.length <= 24;

  const handleCopy = useCallback(async () => {
    if (!trimmedText) return;
    try {
      await navigator.clipboard.writeText(trimmedText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // silent fail
    }
  }, [trimmedText]);

  return (
    <div className="group/user mb-0.5 flex items-center justify-end gap-1">
      {/* Action buttons - vertically centered to the bubble */}
      {hasText && (
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 group-hover/user:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={handleCopy}
            aria-label="Copy message"
            className={cn(
              "flex h-6 w-6 items-center justify-center rounded-lg",
              "text-muted-foreground/70 hover:text-foreground hover:bg-muted",
              "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            )}
          >
            {copied
              ? <CheckIcon className="h-3.5 w-3.5 text-emerald-500" />
              : <CopyIcon className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}

      <div
        className={cn(
          "max-w-[80%] rounded-2xl bg-primary/8 dark:bg-primary/10",
          hasAttachments && hasText
            ? "px-4 py-2.5"
            : isShortSingleLine
              ? "px-4 py-1.5"
              : "px-4 py-2",
        )}
      >
        {/* Attachments */}
        {hasAttachments && (
          <div className={cn(
            "flex flex-wrap items-center gap-1.5",
            hasText && "mb-2 pb-2 border-b border-primary/10"
          )}>
            {message.attachments!.map((attachment) => (
              <AttachmentChip key={attachment.id} attachment={attachment} />
            ))}
          </div>
        )}

        {/* User message */}
        {hasText && (
          <p className={cn(
            "type-size-14 text-foreground whitespace-pre-wrap break-words leading-[1.5]",
            // Tighter line height for multi-line messages
            isMultiLine && "leading-[1.55]"
          )}>
            {parseMentions(textContent)}
          </p>
        )}
      </div>
    </div>
  );
};

export const UserMessageHeader = memo(UserMessageHeaderComponent);
UserMessageHeader.displayName = "UserMessageHeader";

// ============================================================================
// AttachmentChip Component
// ============================================================================

type AttachmentChipProps = {
  attachment: {
    id: string;
    name: string;
    contentType?: string;
    fileSize?: number;
  };
};

const AttachmentChip: FC<AttachmentChipProps> = ({ attachment }) => {
  return (
    <div className="flex items-center gap-1.5 rounded-xl border border-border/50 bg-background/60 px-2 py-1 type-nav-meta shadow-sm">
      <div className="rounded-full bg-primary/10 p-1 text-primary shrink-0">
        <FileText className="h-3 w-3" />
      </div>
      <span className="truncate max-w-[150px] font-medium text-foreground/90">{attachment.name}</span>
    </div>
  );
};
