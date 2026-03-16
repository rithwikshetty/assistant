
/**
 * Skill tool result display components
 *
 * Shows skill name, content preview, and full markdown content when expanded
 * so users can see exactly what instructions the model received.
 */

import { useState, type FC } from "react";
import { Stack, CaretRight, BookOpen, PuzzlePiece } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  parseSkillResultPayload,
  type SkillResultPayload,
} from "@/lib/contracts/chat-specialized-tools";
import {
  parseLoadSkillToolArguments,
  type LoadSkillToolArguments,
} from "@/lib/contracts/chat-tool-arguments";

const ICON_COLOR = "text-teal-600 dark:text-teal-400";

// ============================================================================
// SkillGroupDisplay - Multiple skill loads grouped together
// ============================================================================

type SkillGroupDisplayProps = {
  parts: MessageContentPart[];
};

function safeParseSkillResult(raw: unknown): SkillResultPayload | null {
  if (raw == null) return null;
  try {
    return parseSkillResultPayload(raw, "skill.result");
  } catch {
    return null;
  }
}

function safeParseSkillArgs(raw: unknown): LoadSkillToolArguments | null {
  if (raw == null) return null;
  try {
    return parseLoadSkillToolArguments(raw, "skill.arguments");
  } catch {
    return null;
  }
}

export const SkillGroupDisplay: FC<SkillGroupDisplayProps> = ({ parts }) => {
  const toolParts = parts.filter((p): p is MessageContentPart & { type: "tool-call" } => p.type === "tool-call");
  const isComplete = toolParts.every(p => p.result !== undefined || p.isError);
  const loadedCount = toolParts.filter((p) => {
    const result = safeParseSkillResult(p.result);
    if (result == null) return false;
    return !result.error;
  }).length;

  return (
    <ExpandableToolResult
      icon={Stack}
      isLoading={!isComplete}
      isComplete={isComplete}
      count={toolParts.length}
      loadingLabel={`Loading ${toolParts.length === 1 ? "skill" : `${toolParts.length} skills`}`}
      completeLabel={() =>
        loadedCount === toolParts.length
          ? `${loadedCount === 1 ? "Skill" : `${loadedCount} skills`} loaded`
          : `${loadedCount}/${toolParts.length} skills loaded`
      }
      emptyLabel="No skills loaded"
      completeIconClassName={ICON_COLOR}
      className="tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        renderEntry={(part) => <SkillEntryDisplay part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// SkillEntryDisplay - Single skill load entry
// ============================================================================

type SkillEntryDisplayProps = {
  part: MessageContentPart & { type: "tool-call" };
};

export const SkillEntryDisplay: FC<SkillEntryDisplayProps> = ({ part }) => {
  const [expanded, setExpanded] = useState(false);
  const result = safeParseSkillResult(part.result);
  const args = safeParseSkillArgs(part.args) ?? undefined;

  // Prefer `name` (actual DB title) over `title` (which is the # heading from content)
  const displayName = result?.name ?? result?.title ?? result?.skill_id ?? args?.skill_id ?? "skill";
  const isModule = result?.is_module ?? false;
  const moduleCount = result?.available_modules?.length ?? 0;
  const hasContent = Boolean(result?.content);
  const hasError = Boolean(result?.error);

  const canExpand = hasContent || hasError;

  return (
    <div className="rounded-lg border border-border/60 bg-card overflow-hidden">
      {/* Header */}
      <button
        type="button"
        onClick={() => canExpand && setExpanded(!expanded)}
        className={cn(
          "group flex h-auto w-full items-center justify-start gap-2 border-0 bg-transparent px-3 py-1.5 text-left transition-colors",
          canExpand && "hover:bg-muted/50 focus-visible:bg-muted/50",
          !canExpand && "cursor-default",
        )}
        aria-expanded={canExpand ? expanded : undefined}
      >
        {isModule ? (
          <PuzzlePiece className={cn("h-3.5 w-3.5 flex-shrink-0", result ? ICON_COLOR : "text-muted-foreground")} />
        ) : (
          <Stack className={cn("h-3.5 w-3.5 flex-shrink-0", result ? ICON_COLOR : "text-muted-foreground")} />
        )}
        <span className="type-size-13 font-medium truncate flex-1 min-w-0">
          {result
            ? `${isModule ? "Module" : "Skill"}: ${displayName}`
            : `Loading: ${args?.skill_id ?? "skill"}`}
        </span>
        {moduleCount > 0 && (
          <span className="inline-flex items-center gap-1 rounded-lg bg-teal-500/10 px-2 py-0.5 type-size-12 font-medium text-teal-600 dark:text-teal-400 flex-shrink-0">
            <BookOpen className="h-3 w-3" />
            {moduleCount}
          </span>
        )}
        {canExpand && (
          <CaretRight className={cn("h-4 w-4 text-muted-foreground transition-transform group-hover:text-foreground flex-shrink-0", expanded && "rotate-90")} />
        )}
      </button>

      {/* Error display */}
      {hasError && (
        <div className="border-t border-destructive/40 bg-destructive/10 px-3 py-2 type-size-14 text-destructive">
          {result?.error}
          {result?.message && (
            <p className="mt-1 type-size-12 text-destructive/70">{result.message}</p>
          )}
        </div>
      )}

      {/* Expanded content */}
      {expanded && hasContent && (
        <div className="border-t border-border/60">
          {/* Skill metadata bar */}
          <div className="flex items-center gap-3 px-4 py-2 bg-muted/30 border-b border-border/40">
            {result?.skill_id && (
              <span className="font-mono type-size-12 text-muted-foreground truncate">
                {result.skill_id}
              </span>
            )}
            {result?.parent_skill && (
              <span className="type-size-12 text-muted-foreground/60">
                in {result.parent_skill}
              </span>
            )}
          </div>

          {/* Skill content — the actual instructions the model receives */}
          <div
            className={cn(
              "max-h-80 overflow-y-auto scrollbar-thin",
            )}
          >
            <div className="px-4 py-3 type-size-14 leading-relaxed text-foreground/80 skill-markdown-compact">
              <MarkdownContent content={result!.content!} />
            </div>
          </div>

          {/* Available modules footer */}
          {moduleCount > 0 && result?.available_modules && (
            <div className="border-t border-border/40 px-4 py-2.5 bg-muted/20">
              <p className="type-size-12 font-medium text-muted-foreground mb-1.5">
                {moduleCount} module{moduleCount !== 1 ? "s" : ""} available
              </p>
              <div className="flex flex-wrap gap-1.5">
                {result.available_modules.map((mod) => (
                  <span
                    key={mod}
                    className="inline-flex items-center rounded-md bg-teal-500/10 px-2 py-0.5 type-size-12 font-mono text-teal-600 dark:text-teal-400"
                  >
                    {mod}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
