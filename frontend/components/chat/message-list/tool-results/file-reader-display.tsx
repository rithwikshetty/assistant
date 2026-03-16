
/**
 * File reader tool result display components
 */

import { useState, type FC } from "react";
import { FileText, CaretRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  parseFileReadResultPayload,
  type FileReadResultPayload,
} from "@/lib/contracts/chat-specialized-tools";

const ICON_COLOR = "text-sky-600 dark:text-sky-400";

// ============================================================================
// FileReaderGroupDisplay - Multiple file reads grouped together
// ============================================================================

type FileReaderGroupDisplayProps = {
  parts: MessageContentPart[];
};

export const FileReaderGroupDisplay: FC<FileReaderGroupDisplayProps> = ({ parts }) => {
  const toolParts = parts.filter((p): p is MessageContentPart & { type: "tool-call" } => p.type === "tool-call");
  const isComplete = toolParts.every(p => p.result !== undefined || p.isError);

  return (
    <ExpandableToolResult
      icon={FileText}
      isLoading={!isComplete}
      isComplete={isComplete}
      count={toolParts.length}
      loadingLabel={`Reading ${toolParts.length} files`}
      completeLabel={() => `Files read (${toolParts.length})`}
      emptyLabel="No files read"
      completeIconClassName={ICON_COLOR}
      className="tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        renderEntry={(part) => <FileReaderEntryDisplay part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// FileReaderEntryDisplay - Single file read entry
// ============================================================================

type FileReaderEntryDisplayProps = {
  part: MessageContentPart & { type: "tool-call" };
};

function safeParseFileReadResult(raw: unknown): FileReadResultPayload | null {
  if (raw == null) return null;
  try {
    return parseFileReadResultPayload(raw, "fileRead.result");
  } catch {
    return null;
  }
}

export const FileReaderEntryDisplay: FC<FileReaderEntryDisplayProps> = ({ part }) => {
  const [expanded, setExpanded] = useState(false);
  const result = safeParseFileReadResult(part.result);
  const displayName = result?.original_filename || result?.filename || "File";
  const content = result?.chunks?.map((chunk) => chunk.content).join("\n") || "";
  const isLong = content.length > 500;

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="group flex h-auto w-full items-center justify-start gap-2 rounded-none rounded-t-lg border-0 bg-transparent px-3 py-2 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted/50"
        aria-expanded={expanded}
      >
        <FileText className={cn("h-4 w-4", result ? ICON_COLOR : "text-muted-foreground")} />
        <span className="flex-1 type-size-14 font-medium truncate">{result ? displayName : "Reading file"}</span>
        {result?.file_type && <span className="type-size-12 text-muted-foreground">{result.file_type}</span>}
        <CaretRight className={cn("h-4 w-4 text-muted-foreground transition-transform group-hover:text-foreground", expanded && "rotate-90")} />
      </button>
      {expanded && result && (
        <div className="border-t border-border/60 px-4 py-3 space-y-2">
          {result.error ? (
            <div className="type-size-14 text-destructive">{result.error}</div>
          ) : (
            <>
              {content && (
                <div
                  className={`rounded bg-muted/50 p-2 font-mono type-size-12 whitespace-pre-wrap text-muted-foreground ${
                    isLong ? "max-h-40 overflow-y-auto" : ""
                  }`}
                >
                  {isLong ? `${content.slice(0, 500)} [truncated]` : content}
                </div>
              )}
              {(result.is_truncated || result.has_more) && (
                <div className="type-size-12 text-muted-foreground">
                  Showing {result.total_length ? `partial of ${result.total_length} characters` : "partial content"}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};
