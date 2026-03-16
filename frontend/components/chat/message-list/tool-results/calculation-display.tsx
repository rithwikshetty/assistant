
/**
 * Calculation tool result display components
 */

import { useState, useMemo, type FC } from "react";
import { Calculator, CaretRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { getToolDisplayName } from "../utils";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  parseCalculationResultPayload,
  type CalculationResultPayload,
} from "@/lib/contracts/chat-grouped-tools";

const ICON_COLOR = "text-emerald-600 dark:text-emerald-400";

// ============================================================================
// CalculationGroupDisplay - Multiple calculations grouped together
// ============================================================================

type CalculationGroupDisplayProps = {
  parts: MessageContentPart[];
};

export const CalculationGroupDisplay: FC<CalculationGroupDisplayProps> = ({ parts }) => {
  const toolParts = parts.filter((p): p is MessageContentPart & { type: "tool-call" } => p.type === "tool-call");
  const total = toolParts.length;
  const isComplete = toolParts.every(p => p.result !== undefined || p.isError);
  const isLoading = !isComplete;

  const loadingLabel = total === 1 ? "Running calculation" : `Running ${total} calculations`;
  const completeLabel = () => `Calculations (${total})`;

  return (
    <ExpandableToolResult
      icon={Calculator}
      isLoading={isLoading}
      isComplete={!isLoading}
      count={total}
      loadingLabel={loadingLabel}
      completeLabel={completeLabel}
      emptyLabel="No calculations"
      completeIconClassName={ICON_COLOR}
      className="space-y-2 tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        renderEntry={(part) => <CalculationSessionEntry part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// CalculationSessionEntry - Single calculation entry
// ============================================================================

type CalculationSessionEntryProps = {
  part: MessageContentPart & { type: "tool-call" };
};

function safeParseCalculationResult(raw: unknown): CalculationResultPayload | null {
  if (raw == null) return null;
  try {
    return parseCalculationResultPayload(raw, "calculation.result");
  } catch {
    return null;
  }
}

export const CalculationSessionEntry: FC<CalculationSessionEntryProps> = ({ part }) => {
  const [expanded, setExpanded] = useState(false);

  const result = safeParseCalculationResult(part.result);
  const hasError = part.isError || result?.error;

  const operationLabel = result?.operation_label || getToolDisplayName(part.toolName);
  const resultDisplay = result?.result?.display;
  const reasoning = result?.reasoning?.trim() || null;
  const details = useMemo(
    () => result?.details?.filter((d) => d?.label && d?.value) ?? [],
    [result?.details],
  );

  // Only show chevron if there's expandable content
  const hasExpandableContent = !hasError && result && (result.explanation || reasoning || details.length > 0);

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      <button
        type="button"
        onClick={() => hasExpandableContent && setExpanded(!expanded)}
        className={cn(
          "group flex h-auto w-full items-center gap-2 rounded-none rounded-t-lg border-0 bg-transparent px-3 py-2 text-left transition-colors",
          hasExpandableContent && "hover:bg-muted/50 focus-visible:bg-muted/50",
          !hasExpandableContent && "cursor-default",
        )}
        aria-expanded={hasExpandableContent ? expanded : undefined}
      >
        <Calculator className={cn("h-4 w-4 flex-shrink-0", result && !hasError ? ICON_COLOR : "text-muted-foreground")} />
        <span className="flex-1 type-size-14 font-medium truncate" title={operationLabel}>
          {result ? operationLabel : "Calculation"}
        </span>
        {resultDisplay && (
          <span className="type-size-14 font-semibold text-emerald-600 dark:text-emerald-400 tabular-nums">{resultDisplay}</span>
        )}
        {hasExpandableContent && (
          <CaretRight className={cn("h-4 w-4 flex-shrink-0 text-muted-foreground transition-transform group-hover:text-foreground", expanded && "rotate-90")} />
        )}
      </button>

      {hasError && (
        <div className="border-t border-destructive/40 bg-destructive/10 px-3 py-2 type-size-14 text-destructive">
          {result?.error || "Calculation failed"}
        </div>
      )}

      {expanded && hasExpandableContent && (
        <div className="border-t border-border/60 px-4 py-3 space-y-2 type-size-14 text-muted-foreground">
          {result.explanation && <p>{result.explanation}</p>}

          {reasoning && <p>{reasoning}</p>}

          {details.length > 0 && (
            <ul className="space-y-0.5">
              {details.map((detail, index) => (
                <li key={index} className="flex justify-between gap-3">
                  <span className="font-medium text-foreground/90">{detail.label}</span>
                  <span>{detail.value}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
