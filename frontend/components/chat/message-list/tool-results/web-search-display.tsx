
/**
 * Web search tool result display components
 *
 * Same sources-first layout as knowledge display.
 * Citations shown as primary content, raw response behind disclosure.
 */

import { useState, useMemo, type FC } from "react";
import { GlobeSimple, CaretRight, MagnifyingGlass } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const ICON_COLOR = "text-orange-600 dark:text-orange-400";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { getHost } from "../utils";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  SourceList,
  ContentDisclosure,
  type SourceItem,
} from "./source-list";
import {
  parseWebSearchResultPayload,
  type WebSearchCitationPayload,
  type WebSearchResultPayload,
} from "@/lib/contracts/chat-grouped-tools";
import {
  parseQueryToolArguments,
  type QueryToolArguments,
} from "@/lib/contracts/chat-tool-arguments";

// ============================================================================
// WebSearchGroupDisplay - Multiple web searches grouped together
// ============================================================================

type WebSearchGroupDisplayProps = {
  parts: MessageContentPart[];
};

export const WebSearchGroupDisplay: FC<WebSearchGroupDisplayProps> = ({ parts }) => {
  const toolParts = parts.filter((p): p is MessageContentPart & { type: "tool-call" } => p.type === "tool-call");
  const totalSources = toolParts.reduce((acc, p) => {
    const result = safeParseWebSearchResult(p.result);
    return acc + (result?.citations?.length || 0);
  }, 0);
  const isComplete = toolParts.every(p => p.result !== undefined);

  return (
    <ExpandableToolResult
      icon={GlobeSimple}
      isLoading={!isComplete}
      isComplete={isComplete}
      count={toolParts.length}
      loadingLabel={`Running ${toolParts.length} web searches`}
      completeLabel={() => `Web searches (${toolParts.length} queries, ${totalSources} sources)`}
      emptyLabel="No web results"
      completeIconClassName={ICON_COLOR}
      className="tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        renderEntry={(part) => <WebSearchEntryDisplay part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// WebSearchEntryDisplay - Single web search entry
// ============================================================================

type WebSearchEntryDisplayProps = {
  part: MessageContentPart & { type: "tool-call" };
};

const WebCitationIcon: FC = () => (
  <GlobeSimple className="h-3.5 w-3.5 text-orange-500 dark:text-orange-400 flex-shrink-0" />
);

function safeParseWebSearchResult(raw: unknown): WebSearchResultPayload | null {
  if (raw == null) return null;
  try {
    return parseWebSearchResultPayload(raw, "webSearch.result");
  } catch {
    return null;
  }
}

function safeParseWebSearchArgs(raw: unknown): QueryToolArguments | null {
  if (raw == null) return null;
  try {
    return parseQueryToolArguments(raw, "webSearch.arguments");
  } catch {
    return null;
  }
}

export const WebSearchEntryDisplay: FC<WebSearchEntryDisplayProps> = ({ part }) => {
  const [expanded, setExpanded] = useState(false);
  const result = safeParseWebSearchResult(part.result);
  const args = safeParseWebSearchArgs(part.args);
  const query = args?.query || "web";
  const citations = useMemo(() => result?.citations || [], [result?.citations]);
  const sourceCount = citations.length || (result?.content.trim() ? 1 : 0);

  // ── Build source items from citations ───────────────────────────────────
  const sourceItems: SourceItem[] = useMemo(() => {
    return citations.map((citation: WebSearchCitationPayload, idx) => {
      const host = getHost(citation.url);
      const label = citation.title || host || citation.url;
      const showHost = host && host !== label;

      return {
        key: `${citation.url}-${citation.index ?? idx}`,
        label,
        href: citation.url,
        secondary: showHost ? host : undefined,
        leading: <WebCitationIcon />,
      };
    });
  }, [citations]);

  return (
    <div className="rounded-lg border border-border/60 bg-card overflow-hidden">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="group flex h-auto w-full items-center justify-start gap-2 border-0 bg-transparent px-3 py-2 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted/50"
        aria-expanded={expanded}
      >
        <GlobeSimple className={cn("h-4 w-4", result ? ICON_COLOR : "text-muted-foreground")} />
        <span className="flex-1 type-size-14 font-medium truncate">Searched: {query}</span>
        <span className="type-size-12 text-muted-foreground">{sourceCount} sources</span>
        <CaretRight className={cn("h-4 w-4 text-muted-foreground transition-transform group-hover:text-foreground", expanded && "rotate-90")} />
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t border-border/60 px-4 py-3 space-y-3">
          {/* Query context */}
          {query && (
            <div className="flex items-center gap-1.5 type-size-12 text-muted-foreground">
              <MagnifyingGlass className="h-3 w-3 flex-shrink-0" />
              <span className="italic truncate">&ldquo;{query}&rdquo;</span>
            </div>
          )}

          {/* Citations (primary content) */}
          <SourceList items={sourceItems} />

          {/* Raw search content (secondary) */}
          <ContentDisclosure
            content={result?.content || ""}
            label="Search response"
          />
        </div>
      )}
    </div>
  );
};
