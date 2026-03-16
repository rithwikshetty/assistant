
/**
 * AssistantMessageContent - Renders assistant message content in order.
 *
 * Content is segmented into:
 * - text parts (rendered directly)
 * - visible tools (rendered directly)
 * - grouped non-visible tool sessions (rendered in-line)
 * - direct reasoning parts (rendered in-line)
 */

import { Fragment, useEffect, useMemo, useState, type FC } from "react";
import { CaretRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import type { ContentSegment, MessageContentPart } from "./types";
import {
  formatWorkedDuration,
  getContentPartStableKey,
  isVisibleToolPart,
  segmentContent,
} from "./utils";
import { ContentPart, TextPart } from "./content-parts";
import { VisibleToolRenderer } from "./tool-results";
import { ToolGroupRenderer } from "./tool-group-renderer";

// ============================================================================
// AssistantMessageContent Component
// ============================================================================

type AssistantMessageContentProps = {
  content: MessageContentPart[];
  messageId?: string;
  conversationId?: string;
  isLast?: boolean;
  messageStatus?: string | null;
  responseLatencyMs?: number | null;
};

type ContentPhase = "worklog" | "final";

const getPartPhase = (part: MessageContentPart): ContentPhase | null => {
  const value = (part as { phase?: unknown }).phase;
  if (value === "worklog" || value === "final") {
    return value;
  }
  return null;
};

const isWorklogCollapsiblePart = (part: MessageContentPart): boolean =>
  // Keep visible tools outside the "Worked" collapse, even when they are phase-tagged as worklog.
  getPartPhase(part) === "worklog" && !isVisibleToolPart(part);

type SegmentRenderCtx = {
  messageId?: string;
  conversationId?: string;
  isLast: boolean;
  keyPrefix: string;
};

type ContentRenderBlock = {
  type: "regular" | "worklog";
  parts: MessageContentPart[];
  key: string;
};

const renderSegments = (
  segments: ContentSegment[],
  ctx: SegmentRenderCtx,
) =>
  segments.map((segment, index) => {
    if (segment.type === "text") {
      return <TextPart key={`${ctx.keyPrefix}-text-${index}`} text={segment.text} />;
    }

    if (segment.type === "divider") {
      return (
        <div
          key={`${ctx.keyPrefix}-divider-${index}-${segment.label}`}
          className="my-2 flex items-center gap-3 text-muted-foreground"
        >
          <span className="h-px flex-1 bg-border/50" />
          <span className="type-size-14 font-medium">{segment.label}</span>
          <span className="h-px flex-1 bg-border/50" />
        </div>
      );
    }

    if (segment.type === "visible-tool") {
      const toolPart = segment.part as MessageContentPart & { type: "tool-call" };
      return (
        <div key={`${ctx.keyPrefix}-visible-tool-${toolPart.toolCallId || index}`} className="w-full min-w-0">
          <VisibleToolRenderer
            part={toolPart}
            messageId={ctx.messageId}
            conversationId={ctx.conversationId}
            isFormStale={!ctx.isLast}
          />
        </div>
      );
    }

    if (segment.type === "tool-group") {
      const firstPart = segment.parts[0];
      const groupStableKey = firstPart ? getContentPartStableKey(firstPart, index) : `empty-${index}`;
      return (
        <div key={`${ctx.keyPrefix}-tool-group-${segment.groupKey}-${groupStableKey}`}>
          <ToolGroupRenderer groupKey={segment.groupKey} parts={segment.parts} />
        </div>
      );
    }

    return (
      <div key={`${ctx.keyPrefix}-part-${getContentPartStableKey(segment.part, index)}`}>
        <ContentPart part={segment.part} />
      </div>
    );
  });

const buildPhasedRenderBlocks = (content: MessageContentPart[]): ContentRenderBlock[] => {
  const blocks: ContentRenderBlock[] = [];
  let currentType: ContentRenderBlock["type"] | null = null;
  let currentParts: MessageContentPart[] = [];
  let blockIndex = 0;

  const flushBlock = () => {
    if (!currentType || currentParts.length === 0) return;
    blocks.push({
      type: currentType,
      parts: currentParts,
      key: `${currentType}-${blockIndex}`,
    });
    blockIndex += 1;
    currentType = null;
    currentParts = [];
  };

  for (const part of content) {
    const nextType: ContentRenderBlock["type"] = isWorklogCollapsiblePart(part) ? "worklog" : "regular";
    if (currentType && currentType !== nextType) {
      flushBlock();
    }
    currentType = nextType;
    currentParts.push(part);
  }

  flushBlock();
  return blocks;
};

type WorklogSectionProps = {
  parts: MessageContentPart[];
  messageId?: string;
  conversationId?: string;
  isLast: boolean;
  messageStatus?: string | null;
  responseLatencyMs?: number | null;
  autoCollapseWhenSettled?: boolean;
  showFinalMessageDivider?: boolean;
};

const WorklogSection: FC<WorklogSectionProps> = ({
  parts,
  messageId,
  conversationId,
  isLast,
  messageStatus,
  responseLatencyMs,
  autoCollapseWhenSettled = true,
  showFinalMessageDivider = false,
}) => {
  const segments = useMemo(() => segmentContent(parts), [parts]);
  const normalizedStatus = (messageStatus || "").toLowerCase();
  const settled =
    !normalizedStatus ||
    normalizedStatus === "completed" ||
    normalizedStatus === "failed" ||
    normalizedStatus === "cancelled";
  const [collapsed, setCollapsed] = useState<boolean>(settled && autoCollapseWhenSettled);

  useEffect(() => {
    if (settled && autoCollapseWhenSettled) {
      setCollapsed(true);
    }
  }, [settled, autoCollapseWhenSettled]);

  const workedLabel =
    typeof responseLatencyMs === "number" && Number.isFinite(responseLatencyMs) && responseLatencyMs > 0
      ? `Worked for ${formatWorkedDuration(responseLatencyMs)}`
      : "Worked";

  if (segments.length === 0) return null;

  return (
    <div className="my-1">
      <button
        type="button"
        onClick={() => setCollapsed((prev) => !prev)}
        className="flex w-full items-center gap-3 text-muted-foreground transition-colors hover:text-foreground"
      >
        <span className="h-px flex-1 bg-border/50" />
        <span className="inline-flex items-center gap-1.5 type-size-14 font-medium">
          {workedLabel}
          <CaretRight
            className={cn(
              "h-3.5 w-3.5 transition-transform duration-200",
              !collapsed && "rotate-90",
            )}
          />
        </span>
        <span className="h-px flex-1 bg-border/50" />
      </button>

      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-300 ease-out",
          collapsed ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100",
        )}
      >
        <div className="overflow-y-hidden overflow-x-visible">
          <div className="mt-3 space-y-1.5">
            {renderSegments(segments, {
              messageId,
              conversationId,
              isLast,
              keyPrefix: "worklog",
            })}
          </div>
          {showFinalMessageDivider && (
            <div className="mt-4 flex items-center gap-3 text-muted-foreground">
              <span className="h-px flex-1 bg-border/50" />
              <span className="type-size-14 font-medium">Final message</span>
              <span className="h-px flex-1 bg-border/50" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const AssistantMessageContent: FC<AssistantMessageContentProps> = ({
  content,
  messageId,
  conversationId,
  isLast = false,
  messageStatus,
  responseLatencyMs,
}) => {
  const normalizedStatus = (messageStatus || "").toLowerCase();
  const isFinalMessageStatus =
    !normalizedStatus ||
    normalizedStatus === "completed" ||
    normalizedStatus === "failed" ||
    normalizedStatus === "cancelled";
  const hasPhaseAnnotations = useMemo(
    () => content.some((part) => getPartPhase(part) !== null),
    [content],
  );
  const renderBlocks = useMemo(
    () =>
      hasPhaseAnnotations
        ? buildPhasedRenderBlocks(content)
        : [{ type: "regular" as const, parts: content, key: "regular-0" }],
    [content, hasPhaseAnnotations],
  );
  const hasRegularRenderableContent = useMemo(
    () => renderBlocks.some(
      (block) => block.type === "regular" && segmentContent(block.parts).length > 0,
    ),
    [renderBlocks],
  );
  const worklogHasFollowingFinalContent = useMemo(() => {
    const byBlockKey = new Map<string, boolean>();

    for (let i = 0; i < renderBlocks.length; i += 1) {
      const block = renderBlocks[i];
      if (block.type !== "worklog") continue;

      let hasFollowingFinalContent = false;
      for (let j = i + 1; j < renderBlocks.length; j += 1) {
        const candidate = renderBlocks[j];
        if (candidate.type !== "regular") continue;
        if (segmentContent(candidate.parts).length === 0) continue;
        if (candidate.parts.some((part) => getPartPhase(part) !== "worklog")) {
          hasFollowingFinalContent = true;
          break;
        }
      }

      byBlockKey.set(block.key, hasFollowingFinalContent);
    }

    return byBlockKey;
  }, [renderBlocks]);
  const renderWorklogInline = !isFinalMessageStatus;

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {renderBlocks.map((block, index) => {
        if (block.type === "worklog" && !renderWorklogInline) {
          return (
            <WorklogSection
              key={`phased-worklog-${block.key}`}
              parts={block.parts}
              messageId={messageId}
              conversationId={conversationId}
              isLast={isLast}
              messageStatus={messageStatus}
              responseLatencyMs={responseLatencyMs}
              autoCollapseWhenSettled={hasRegularRenderableContent}
              showFinalMessageDivider={Boolean(worklogHasFollowingFinalContent.get(block.key))}
            />
          );
        }

        const keyPrefix =
          block.type === "worklog"
            ? `phased-worklog-inline-${block.key}`
            : `phased-regular-${block.key}`;

        return (
          <Fragment key={`${keyPrefix}-${index}`}>
            {renderSegments(segmentContent(block.parts), {
              messageId,
              conversationId,
              isLast,
              keyPrefix,
            })}
          </Fragment>
        );
      })}
    </div>
  );
};
