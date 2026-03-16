
/**
 * AssistantActionBar - Action buttons for assistant messages
 */

import { useState, useEffect, useMemo, useCallback, type FC, type ReactElement } from "react";
import {
  Copy as CopyIcon, ThumbsUp as ThumbsUpIcon, ThumbsDown as ThumbsDownIcon, Clock as Clock3Icon, Check as CheckIcon, Books as LibraryIcon, DownloadSimple as Download, FileArrowDown as FileOutput, GitBranch, SpinnerGap as Loader2,
} from "@phosphor-icons/react";
import * as Popover from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";
import { TooltipIconButton } from "@/components/tools/tooltip-icon-button";
import { useToast } from "@/components/ui/toast";
import { MessageFeedbackDialog } from "@/components/feedback/message-feedback-dialog";
import { deleteMessageFeedback, type MessageFeedbackRating } from "@/lib/api/feedback";
import { branchConversation, conversationResponseToSummary } from "@/lib/api/auth";
import { useConversations } from "@/hooks/use-conversations";
import { useNavigate } from "react-router-dom";
import { useCopyMessageContent } from "@/hooks/useCopyMessageContent";
import { collectMessageInsights } from "@/lib/insights/collect";
import { useOptionalInsightSidebar } from "@/components/chat/insights/insight-sidebar-context";
import { TOOL } from "@/lib/tools/constants";
import { upsertConversationSummary } from "@/lib/chat/conversation-list";
import type { Message } from "./types";
import { formatDuration, METRIC_CONTAINER_CLASS, METRIC_ITEM_CLASS } from "./utils";

// ============================================================================
// Generated file types & helpers
// ============================================================================

type GeneratedFile = {
  file_id?: string;
  filename?: string;
  file_type?: string;
  file_size?: number;
  download_url?: string;
  download_path?: string;
};

const isRecord = (v: unknown): v is Record<string, unknown> =>
  Boolean(v) && typeof v === "object" && !Array.isArray(v);

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/** Walk message content parts and collect generated files from all execute_code tool calls */
const collectGeneratedFiles = (content: unknown[]): GeneratedFile[] => {
  const files: GeneratedFile[] = [];
  const seen = new Set<string>();

  for (const part of content) {
    if (!isRecord(part)) continue;
    if (part.type !== "tool-call" || part.toolName !== TOOL.EXECUTE_CODE) continue;

    const result = part.result;
    if (!isRecord(result)) continue;

    const generated = result.generated_files;
    if (!Array.isArray(generated)) continue;

    for (const file of generated) {
      if (!isRecord(file)) continue;
      const key = (file.file_id as string) ?? (file.filename as string) ?? "";
      if (!key || seen.has(key)) continue;
      seen.add(key);
      files.push(file as GeneratedFile);
    }
  }
  return files;
};

// ============================================================================
// GeneratedFilesMetric - Popover for downloading code-execution output files
// ============================================================================

const GeneratedFilesMetric: FC<{ files: GeneratedFile[] }> = ({ files }) => {
  const count = files.length;

  // Single file → direct download, no popover
  if (count === 1) {
    const file = files[0];
    return (
      <a
        href={file.download_url}
        download={file.filename}
        className={cn(
          METRIC_ITEM_CLASS,
          "h-auto border-0 bg-transparent p-0 rounded-none type-size-10 font-normal text-inherit transition-colors",
          "hover:text-foreground focus-visible:text-foreground no-underline",
        )}
        aria-label={`Download ${file.filename}`}
      >
        <Download className="h-[10px] w-[10px]" aria-hidden="true" />
        {file.filename || "1 file"}
      </a>
    );
  }

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            METRIC_ITEM_CLASS,
            "h-auto border-0 bg-transparent p-0 rounded-none type-size-10 font-normal text-inherit transition-colors",
            "hover:text-foreground focus-visible:text-foreground",
          )}
          aria-label={`${count} generated files`}
        >
          <Download className="h-[10px] w-[10px]" aria-hidden="true" />
          {count} file{count === 1 ? "" : "s"}
        </button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          side="top"
          sideOffset={6}
          align="start"
          className="z-50 w-64 rounded-xl border bg-popover text-popover-foreground shadow-lg animate-in fade-in-0 zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-border/40">
            <span className="type-size-10 font-medium text-muted-foreground uppercase tracking-wide">
              Files
            </span>
            <button
              type="button"
              className="inline-flex items-center gap-1 type-size-10 text-primary hover:text-primary/80 transition-colors"
              onClick={() => {
                for (const file of files) {
                  if (!file.download_url) continue;
                  const a = document.createElement("a");
                  a.href = file.download_url;
                  a.download = file.filename || `output.${file.file_type || "file"}`;
                  a.click();
                }
              }}
            >
              <Download className="h-2.5 w-2.5" />
              Download all
            </button>
          </div>
          <ul className="max-h-48 overflow-y-auto py-1">
            {files.map((file, idx) => {
              const name = file.filename || `output.${file.file_type || "file"}`;
              return (
                <li key={file.file_id ?? idx}>
                  <a
                    href={file.download_url}
                    download={name}
                    className="flex items-center gap-2 px-3 py-1.5 transition-colors hover:bg-muted/60 no-underline"
                  >
                    <FileOutput className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate type-size-12 text-foreground">
                      {name}
                    </span>
                    {typeof file.file_size === "number" && (
                      <span className="shrink-0 type-size-10 text-muted-foreground">
                        {formatFileSize(file.file_size)}
                      </span>
                    )}
                  </a>
                </li>
              );
            })}
          </ul>
          <Popover.Arrow className="fill-popover" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
};

// ============================================================================
// AssistantActionBar Component
// ============================================================================

type AssistantActionBarProps = {
  message: Message;
  conversationId?: string;
  viewerIsOwner?: boolean;
  canGiveFeedback?: boolean;
  isLast?: boolean;
  isStreaming?: boolean;
};

export const AssistantActionBar: FC<AssistantActionBarProps> = ({
  message,
  conversationId,
  canGiveFeedback = true,
  isLast = false,
  isStreaming = false,
}) => {
  const { addToast } = useToast();
  const navigate = useNavigate();
  const { refreshConversations, updateConversations } = useConversations();
  const [selectedRating, setSelectedRating] = useState<MessageFeedbackRating | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isBranching, setIsBranching] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingRating, setPendingRating] = useState<MessageFeedbackRating | null>(null);

  // Insight sidebar for sources
  const insightSidebar = useOptionalInsightSidebar();

  // Use the rich text copy hook
  const { copied, handleCopy } = useCopyMessageContent();

  // Detect if message was stopped early
  const stoppedEarly = useMemo(() => {
    return message.finishReason === "cancelled";
  }, [message.finishReason]);

  const messageId = message.id;
  const feedbackMessageId = messageId;

  // Extract current feedback rating
  const currentFeedbackRating = useMemo(() => {
    const rating = message.userFeedbackRating;
    return rating === "up" || rating === "down" ? (rating as MessageFeedbackRating) : null;
  }, [message.userFeedbackRating]);

  useEffect(() => {
    setSelectedRating(currentFeedbackRating);
  }, [currentFeedbackRating]);

  // Extract duration
  const durationMs = useMemo(() => {
    if (typeof message.responseLatencyMs === "number" && Number.isFinite(message.responseLatencyMs)) {
      return message.responseLatencyMs;
    }
    return null;
  }, [message.responseLatencyMs]);

  // Collect source count from message insights - memoize the message object separately
  const insightMessage = useMemo(() => ({
    content: message.content,
    metadata: message.metadata,
  }), [message.content, message.metadata]);

  const sourceCount = useMemo(() => {
    const meta = collectMessageInsights(insightMessage);
    const total = (meta?.total ?? 0) + (meta?.ratesCount ?? 0) + (meta?.bcisIndices?.length ?? 0) + (meta?.projectDetails?.length ?? 0);
    return Number.isFinite(total) ? total : 0;
  }, [insightMessage]);

  const showInsights = sourceCount > 0;

  // Collect generated files from execute_code tool calls
  const generatedFiles = useMemo(
    () => collectGeneratedFiles(message.content as unknown[]),
    [message.content],
  );

  const handleInsightsClick = useCallback(() => {
    if (!showInsights || !messageId || !insightSidebar) return;

    // Check if this message's panel is already open
    const isActive = insightSidebar.isOpen && insightSidebar.data?.messageId === messageId;
    if (isActive) {
      insightSidebar.closeSidebar();
      return;
    }
    insightSidebar.openSidebar({
      message: insightMessage,
      messageId: messageId,
      sourceCount,
    });
  }, [showInsights, messageId, insightMessage, sourceCount, insightSidebar]);

  // Handle feedback
  const handleFeedback = useCallback(
    async (nextRating: MessageFeedbackRating) => {
      if (!feedbackMessageId || isSubmitting || !canGiveFeedback) return;

      const previous = selectedRating;

      // If clicking the same rating, delete feedback
      if (previous === nextRating) {
        setIsSubmitting(true);
        let dispatchedRequiresFeedback = false;
        try {
          // Dispatch event to indicate feedback status change
          if (conversationId) {
            try {
              window.dispatchEvent(
                new CustomEvent("frontend:conversationFeedbackStatus", {
                  detail: { conversationId, requiresFeedback: true },
                }),
              );
              dispatchedRequiresFeedback = true;
            } catch { }
          }
          const response = await deleteMessageFeedback(feedbackMessageId);
          setSelectedRating(null);
          // Update feedback status based on response
          if (conversationId) {
            try {
              window.dispatchEvent(
                new CustomEvent("frontend:conversationFeedbackStatus", {
                  detail: {
                    conversationId,
                    requiresFeedback: response?.conversation_requires_feedback ?? true,
                  },
                }),
              );
            } catch { }
          }
        } catch (error) {
          setSelectedRating(previous);
          // Revert feedback status if we dispatched it
          if (conversationId && dispatchedRequiresFeedback) {
            try {
              window.dispatchEvent(
                new CustomEvent("frontend:conversationFeedbackStatus", {
                  detail: { conversationId, requiresFeedback: false },
                }),
              );
            } catch { }
          }
          const errorMessage = error instanceof Error ? error.message : "Please try again.";
          addToast({ title: "Couldn't delete feedback", description: errorMessage, type: "error" });
        } finally {
          setIsSubmitting(false);
        }
        return;
      }

      // Open dialog for feedback
      setPendingRating(nextRating);
      setDialogOpen(true);
    },
    [addToast, feedbackMessageId, canGiveFeedback, conversationId, isSubmitting, selectedRating],
  );

  const handleDialogClose = useCallback(() => {
    setDialogOpen(false);
    setPendingRating(null);
  }, []);

  const handleDialogSuccess = useCallback(() => {
    if (pendingRating) {
      setSelectedRating(pendingRating);
    }
    setDialogOpen(false);
    setPendingRating(null);
  }, [pendingRating]);

  // Handle branch
  const handleBranch = useCallback(async () => {
    if (!conversationId || !messageId || isBranching) return;

    setIsBranching(true);
    try {
      const response = await branchConversation(conversationId, messageId);
      const summary = conversationResponseToSummary(response);
      try {
        window.dispatchEvent(
          new CustomEvent("frontend:conversationCreated", {
            detail: { conversation: response },
          }),
        );
      } catch { }
      updateConversations((current) => upsertConversationSummary(current, summary).next);
      refreshConversations?.();

      const href = summary.project_id
        ? `/projects/${summary.project_id}/chat/${summary.id}`
        : `/chat/${summary.id}`;
      navigate(href);

      addToast({ type: "success", title: "Conversation branched" });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Please try again.";
      addToast({ type: "error", title: "Failed to branch", description: errorMessage });
    } finally {
      setIsBranching(false);
    }
  }, [conversationId, messageId, isBranching, updateConversations, refreshConversations, navigate, addToast]);

  const disableFeedback = !feedbackMessageId || isSubmitting || !canGiveFeedback;
  const isThumbsUp = selectedRating === "up";
  const isThumbsDown = selectedRating === "down";
  const showThumbsUp = selectedRating === null || isThumbsUp;
  const showThumbsDown = selectedRating === null || isThumbsDown;
  const showDuration = !isStreaming && durationMs !== null && durationMs > 0;

  // Hide action bar while streaming or while message is incomplete (e.g. awaiting_input on page refresh)
  const isIncomplete = !!message.status && message.status !== "completed" && message.status !== "failed" && message.status !== "cancelled";
  const hideWhileRunning = isLast && (isStreaming || isIncomplete);

  // Build metrics array like the original implementation
  const metrics = [
    showDuration ? (
      <span key="duration" className={METRIC_ITEM_CLASS}>
        <Clock3Icon className="h-[10px] w-[10px]" aria-hidden="true" />
        {formatDuration(durationMs ?? 0)}
      </span>
    ) : null,
    showInsights ? (
      <button
        key="sources"
        type="button"
        onClick={handleInsightsClick}
        className={cn(
          METRIC_ITEM_CLASS,
          "h-auto border-0 bg-transparent p-0 rounded-none type-size-10 font-normal text-inherit transition-colors",
          "hover:text-foreground focus-visible:text-foreground",
        )}
        aria-label="View sources"
      >
        <LibraryIcon className="h-[10px] w-[10px]" aria-hidden="true" />
        {sourceCount} source{sourceCount === 1 ? "" : "s"}
      </button>
    ) : null,
    generatedFiles.length > 0 ? (
      <GeneratedFilesMetric key="files" files={generatedFiles} />
    ) : null,
  ];

  const metricNodes = metrics.filter((metric): metric is ReactElement => Boolean(metric));

  // Interleave metrics with separators
  const interleavedMetrics = metricNodes.flatMap((metric, index) => {
    const parts: ReactElement[] = [metric];
    if (index < metricNodes.length - 1) {
      parts.push(
        <span key={`sep-${index}`} className="h-3 border-l border-border/40" aria-hidden="true" />,
      );
    }
    return parts;
  });

  // Don't render if hidden while running
  if (hideWhileRunning) {
    return null;
  }

  return (
    <>
      <div
        className={cn(
          "assistant-action-bar text-muted-foreground flex gap-0.5 col-start-3 row-start-2 -ml-1 mt-1",
          "opacity-0 group-hover:opacity-100 transition-opacity pointer-events-auto"
        )}
      >
        {/* Copy button */}
        <TooltipIconButton
          tooltip={copied ? "Copied!" : "Copy"}
          sizeClass="micro"
          aria-label="Copy message"
          onClick={handleCopy}
        >
          {copied ? <CheckIcon className="h-3.5 w-3.5" /> : <CopyIcon className="h-3.5 w-3.5" />}
        </TooltipIconButton>

        {/* Thumbs up */}
        {showThumbsUp && (
          <TooltipIconButton
            tooltip="Good response"
            sizeClass="micro"
            aria-label="Thumbs up"
            aria-pressed={isThumbsUp}
            disabled={disableFeedback}
            onClick={() => handleFeedback("up")}
            className={cn(isThumbsUp && "text-emerald-600 dark:text-emerald-400")}
          >
            <ThumbsUpIcon className="h-3.5 w-3.5" />
          </TooltipIconButton>
        )}

        {/* Thumbs down */}
        {showThumbsDown && (
          <TooltipIconButton
            tooltip="Needs improvement"
            sizeClass="micro"
            aria-label="Thumbs down"
            aria-pressed={isThumbsDown}
            disabled={disableFeedback}
            onClick={() => handleFeedback("down")}
            className={cn(isThumbsDown && "text-rose-600 dark:text-rose-400")}
          >
            <ThumbsDownIcon className="h-3.5 w-3.5" />
          </TooltipIconButton>
        )}

        {/* Branch button */}
        {conversationId && (
          <TooltipIconButton
            tooltip={isBranching ? "Branching conversation" : "Branch conversation"}
            sizeClass="micro"
            aria-label="Branch conversation"
            disabled={isBranching}
            onClick={handleBranch}
          >
            {isBranching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitBranch className="h-3.5 w-3.5" />}
          </TooltipIconButton>
        )}

        {/* Metrics (duration + sources) */}
        {interleavedMetrics.length > 0 && (
          <div className={METRIC_CONTAINER_CLASS}>
            {interleavedMetrics}
          </div>
        )}

        {/* Stopped early badge */}
        {stoppedEarly && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-300/60 bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200 px-2 py-[2px] type-size-10 font-medium">
            Stopped early
          </span>
        )}
      </div>

      {/* Feedback dialog */}
      {feedbackMessageId && pendingRating && (
        <MessageFeedbackDialog
          open={dialogOpen}
          onClose={handleDialogClose}
          messageId={feedbackMessageId}
          conversationId={conversationId}
          rating={pendingRating}
          onSuccess={handleDialogSuccess}
        />
      )}
    </>
  );
};
