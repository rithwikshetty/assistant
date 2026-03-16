
/**
 * Execute code tool result display components
 */

import { useState, type FC } from "react";
import { Code, CaretRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  parseExecuteCodeResultPayload,
  type ExecuteCodeResultPayload,
} from "@/lib/contracts/chat-specialized-tools";

const ICON_COLOR = "text-pink-600 dark:text-pink-400";

// ============================================================================
// ExecuteCodeGroupDisplay - Multiple code executions grouped together
// ============================================================================

type ExecuteCodeGroupDisplayProps = {
  parts: MessageContentPart[];
};

function safeParseExecuteCodeResult(raw: unknown): ExecuteCodeResultPayload | null {
  if (raw == null) return null;
  try {
    return parseExecuteCodeResultPayload(raw, "executeCode.result");
  } catch {
    return null;
  }
}

export const ExecuteCodeGroupDisplay: FC<ExecuteCodeGroupDisplayProps> = ({ parts }) => {
  const toolParts = parts.filter((p): p is MessageContentPart & { type: "tool-call" } => p.type === "tool-call");
  const isComplete = toolParts.every(p => p.result !== undefined || p.isError);
  const successCount = toolParts.filter(p => {
    const r = safeParseExecuteCodeResult(p.result);
    return r?.success !== false;
  }).length;
  const totalTime = toolParts.reduce((acc, p) => {
    const r = safeParseExecuteCodeResult(p.result);
    return acc + (r?.execution_time_ms ?? 0);
  }, 0);
  const timePart = totalTime > 0 ? `, ${(totalTime / 1000).toFixed(1)}s` : "";

  return (
    <ExpandableToolResult
      icon={Code}
      isLoading={!isComplete}
      isComplete={isComplete}
      count={toolParts.length}
      loadingLabel={`Running ${toolParts.length} code blocks`}
      completeLabel={() =>
        isComplete && successCount < toolParts.length
          ? `Code executions (${toolParts.length}, ${toolParts.length - successCount} failed${timePart})`
          : `Code executions (${toolParts.length}${timePart})`
      }
      emptyLabel="No code executions"
      completeIconClassName={ICON_COLOR}
      className="tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        renderEntry={(part) => <ExecuteCodeEntryDisplay part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// ExecuteCodeEntryDisplay - Single code execution entry
// ============================================================================

type ExecuteCodeEntryDisplayProps = {
  part: MessageContentPart & { type: "tool-call" };
};

export const ExecuteCodeEntryDisplay: FC<ExecuteCodeEntryDisplayProps> = ({ part }) => {
  const [expanded, setExpanded] = useState(false);
  const result = safeParseExecuteCodeResult(part.result);
  const ok = result?.success ?? true;
  const timeMs = result?.execution_time_ms;
  const timePart = typeof timeMs === "number" ? ` in ${(timeMs / 1000).toFixed(1)}s` : "";
  const fileCount = result?.generated_files?.length ?? 0;

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      <button
        type="button"
        onClick={() => result && setExpanded(!expanded)}
        className={cn(
          "group flex h-auto w-full items-center justify-start gap-2 rounded-none rounded-t-lg border-0 bg-transparent px-3 py-2 text-left transition-colors",
          result && "hover:bg-muted/50 focus-visible:bg-muted/50",
          !result && "cursor-default",
        )}
        aria-expanded={result ? expanded : undefined}
      >
        <Code className={cn("h-4 w-4", result ? ICON_COLOR : "text-muted-foreground")} />
        <span className="flex-1 type-size-14 font-medium truncate">
          {result
            ? ok
              ? `Code executed${timePart}${fileCount ? ` | ${fileCount} file${fileCount > 1 ? "s" : ""}` : ""}`
              : `Code failed${timePart}`
            : "Running code"}
        </span>
        {result && (
          <>
            <span className={cn("inline-flex items-center gap-1 type-size-12 font-medium", ok ? "text-emerald-600" : "text-destructive")}>
              <span className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-emerald-500" : "bg-destructive")} />
              {ok ? "OK" : "Fail"}
            </span>
            <CaretRight className={cn("h-4 w-4 text-muted-foreground transition-transform group-hover:text-foreground", expanded && "rotate-90")} />
          </>
        )}
      </button>
      {expanded && result && (
        <div className="border-t border-border/60 px-4 py-3 space-y-2">
          {result.code && (
            <details className="group">
              <summary className="cursor-pointer select-none type-size-12 uppercase tracking-wide text-muted-foreground hover:text-foreground/70">
                Code {(result.retries_used ?? 0) > 0 ? "(auto-fixed)" : ""}
              </summary>
              <pre className="mt-1 max-h-60 overflow-y-auto rounded bg-muted/50 p-2 font-mono type-size-12 whitespace-pre-wrap text-foreground/90">
                {result.code.length > 3000 ? `${result.code.slice(0, 3000)}\n[truncated]` : result.code}
              </pre>
            </details>
          )}
          {result.stdout && (
            <details className="group" open={!fileCount}>
              <summary className="cursor-pointer select-none type-size-12 uppercase tracking-wide text-muted-foreground hover:text-foreground/70">Output</summary>
              <pre className="mt-1 max-h-60 overflow-y-auto rounded bg-muted/50 p-2 font-mono type-size-12 whitespace-pre-wrap text-foreground/90">
                {result.stdout.length > 2000 ? `${result.stdout.slice(0, 2000)} [truncated]` : result.stdout}
              </pre>
            </details>
          )}
          {result.stderr && (
            <details className="group" open>
              <summary className="cursor-pointer select-none type-size-12 uppercase tracking-wide text-destructive/80 hover:text-destructive">Error</summary>
              <pre className="mt-1 max-h-40 overflow-y-auto rounded bg-destructive/5 p-2 font-mono type-size-12 whitespace-pre-wrap text-destructive">
                {result.stderr.length > 1500 ? result.stderr.slice(-1500) : result.stderr}
              </pre>
            </details>
          )}
          {result.error && !result.stderr && (
            <div className="type-size-14 text-destructive">{result.error}</div>
          )}
        </div>
      )}
    </div>
  );
};
