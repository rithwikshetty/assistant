
/**
 * Tasks tool result display components
 */

import { useState, type FC } from "react";
import { ListChecks, CaretRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  parseTasksResultPayload,
  type TasksResultPayload,
} from "@/lib/contracts/chat-grouped-tools";

const ICON_COLOR = "text-orange-600 dark:text-orange-400";

// ============================================================================
// TasksGroupDisplay - Multiple task operations grouped together
// ============================================================================

type TasksGroupDisplayProps = {
  parts: MessageContentPart[];
};

export const TasksGroupDisplay: FC<TasksGroupDisplayProps> = ({ parts }) => {
  const toolParts = parts.filter((p): p is MessageContentPart & { type: "tool-call" } => p.type === "tool-call");
  const isComplete = toolParts.every(p => p.result !== undefined || p.isError);

  return (
    <ExpandableToolResult
      icon={ListChecks}
      isLoading={!isComplete}
      isComplete={isComplete}
      count={toolParts.length}
      loadingLabel={`Working on ${toolParts.length} tasks`}
      completeLabel={() => `Tasks (${toolParts.length} operations)`}
      emptyLabel="No task operations"
      completeIconClassName={ICON_COLOR}
      className="tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        renderEntry={(part) => <TasksEntryDisplay part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// TasksEntryDisplay - Single task operation entry
// ============================================================================

type TasksEntryDisplayProps = {
  part: MessageContentPart & { type: "tool-call" };
};

function safeParseTasksResult(raw: unknown): TasksResultPayload | null {
  if (raw == null) return null;
  try {
    return parseTasksResultPayload(raw, "tasks.result");
  } catch {
    return null;
  }
}

const getTaskEntryLabel = (result?: TasksResultPayload | null): string => {
  if (!result) return "Working on task";
  if (result.message) return result.message;
  if (result.action) return `Task ${result.action}`;
  if (result.task?.title) return result.task.title;
  const items = result.items ?? [];
  if (items.length > 0) return `${items.length} task${items.length > 1 ? "s" : ""}`;
  return "Task operation";
};

export const TasksEntryDisplay: FC<TasksEntryDisplayProps> = ({ part }) => {
  const [expanded, setExpanded] = useState(false);
  const result = safeParseTasksResult(part.result);
  const label = getTaskEntryLabel(result);
  const hasContent = result && !result.error && (result.task || result.items?.length || result.comments?.length);

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      <button
        type="button"
        onClick={() => hasContent && setExpanded(!expanded)}
        className={cn(
          "group flex h-auto w-full items-center justify-start gap-2 rounded-none rounded-t-lg border-0 bg-transparent px-3 py-2 text-left transition-colors",
          hasContent && "hover:bg-muted/50 focus-visible:bg-muted/50",
          !hasContent && "cursor-default",
        )}
        aria-expanded={hasContent ? expanded : undefined}
      >
        <ListChecks className={cn("h-4 w-4", result ? ICON_COLOR : "text-muted-foreground")} />
        <span className="flex-1 type-size-14 font-medium truncate">{label}</span>
        {hasContent && (
          <CaretRight className={cn("h-4 w-4 text-muted-foreground transition-transform group-hover:text-foreground", expanded && "rotate-90")} />
        )}
      </button>
      {result?.error && (
        <div className="border-t border-destructive/40 bg-destructive/10 px-3 py-2 type-size-14 text-destructive">
          {result.error}
        </div>
      )}
      {expanded && hasContent && (
        <div className="border-t border-border/60 px-4 py-3 space-y-2 type-size-14 text-muted-foreground">
          {result.task && (
            <div>
              {result.task.title && <div className="font-medium text-foreground">{result.task.title}</div>}
            </div>
          )}
          {(() => {
            const items = result.items ?? [];
            if (!Array.isArray(items) || items.length === 0) return null;
            return (
              <ul className="space-y-1">
                {items.map((task, idx: number) => {
                  const title = typeof task?.title === "string" ? task.title : undefined;
                  return (
                    <li key={idx} className="type-size-12">
                      {title || `Task ${idx + 1}`}
                    </li>
                  );
                })}
              </ul>
            );
          })()}
          {result.comments && result.comments.length > 0 && (
            <ul className="space-y-1">
              {result.comments.map((comment, index) => (
                <li key={comment.id || index} className="type-size-12">
                  {comment.content || `Comment ${index + 1}`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
