
/**
 * Knowledge search tool result display components
 *
 * Sources-first layout: linked file references are the primary content.
 * Raw retrieved text is available behind a secondary disclosure.
 */

import { useState, useMemo, type FC } from "react";
import { BookOpen, CaretRight, MagnifyingGlass } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import {
  buildPageSummary,
  buildSourceIdentityKey,
  normalizePageLabel,
  resolveSourceUrl,
} from "@/lib/insights/source-normalization";

const ICON_COLOR = "text-amber-600 dark:text-amber-400";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import type { MessageContentPart } from "../types";
import { getToolDisplayName } from "../utils";
import { GroupedToolRunHistory } from "./grouped-tool-run-history";
import {
  SourceList,
  FileTypeBadge,
  ContentDisclosure,
  type SourceItem,
} from "./source-list";
import {
  parseKnowledgeResultPayload,
  type KnowledgeResultPayload,
  type KnowledgeSourcePayload,
} from "@/lib/contracts/chat-grouped-tools";
import {
  parseQueryToolArguments,
  type QueryToolArguments,
} from "@/lib/contracts/chat-tool-arguments";

// ============================================================================
// KnowledgeGroupDisplay - Multiple knowledge searches grouped together
// ============================================================================

type KnowledgeGroupDisplayProps = {
  parts: MessageContentPart[];
};

export const KnowledgeGroupDisplay: FC<KnowledgeGroupDisplayProps> = ({
  parts,
}) => {
  const toolParts = parts.filter(
    (p): p is MessageContentPart & { type: "tool-call" } =>
      p.type === "tool-call",
  );
  const totalResults = toolParts.reduce((acc, p) => {
    const result = safeParseKnowledgeResult(p.result);
    return (
      acc +
      (result?.sources?.length ||
        result?.results?.length ||
        result?.total_nodes ||
        0)
    );
  }, 0);
  const isComplete = toolParts.every((p) => p.result !== undefined);

  return (
    <ExpandableToolResult
      icon={BookOpen}
      isLoading={!isComplete}
      isComplete={isComplete}
      count={totalResults}
      loadingLabel={`Searching ${toolParts.length} knowledge bases`}
      completeLabel={() => `Knowledge search (${totalResults} results)`}
      emptyLabel="No knowledge results"
      completeIconClassName={ICON_COLOR}
      className="tool-connectable"
    >
      <GroupedToolRunHistory
        parts={toolParts}
        className="space-y-3"
        renderEntry={(part) => <KnowledgeEntryDisplay part={part} />}
      />
    </ExpandableToolResult>
  );
};

// ============================================================================
// KnowledgeEntryDisplay - Single knowledge search entry
// ============================================================================

type KnowledgeEntryDisplayProps = {
  part: MessageContentPart & { type: "tool-call" };
};

function safeParseKnowledgeResult(raw: unknown): KnowledgeResultPayload | null {
  if (raw == null) return null;
  try {
    return parseKnowledgeResultPayload(raw, "knowledge.result");
  } catch {
    return null;
  }
}

function safeParseKnowledgeArgs(raw: unknown): QueryToolArguments | null {
  if (raw == null) return null;
  try {
    return parseQueryToolArguments(raw, "knowledge.arguments");
  } catch {
    return null;
  }
}

export const KnowledgeEntryDisplay: FC<KnowledgeEntryDisplayProps> = ({
  part,
}) => {
  const [expanded, setExpanded] = useState(false);

  const result = safeParseKnowledgeResult(part.result);
  const args = safeParseKnowledgeArgs(part.args);
  const query = result?.query || args?.query || "";

  const sources = useMemo(() => result?.sources || [], [result?.sources]);
  const projectResults = useMemo(
    () => result?.results || [],
    [result?.results],
  );
  const files = useMemo(() => result?.files || [], [result?.files]);
  const sourceCount =
    sources.length || projectResults.length || result?.total_nodes || 0;

  const rawContent = result?.content || result?.message || "";

  // ── Build source items for SourceList ───────────────────────────────────
  const sourceItems: SourceItem[] = useMemo(() => {
    const itemsByIdentity = new Map<
      string,
      {
        identityKey: string;
        file: string;
        href?: string;
        pages: Set<string>;
      }
    >();
    const filesWithSourceMetadata = new Set<string>();

    const register = ({
      fileRaw,
      pageRaw,
      hrefRaw,
      fromSource,
    }: {
      fileRaw: unknown;
      pageRaw?: unknown;
      hrefRaw?: unknown;
      fromSource?: boolean;
    }) => {
      const file = typeof fileRaw === "string" ? fileRaw.trim() : "";
      if (!file) return;

      const normalizedFileName = file.toLowerCase();
      const href =
        typeof hrefRaw === "string" && hrefRaw.trim()
          ? hrefRaw.trim()
          : undefined;
      const page = normalizePageLabel(pageRaw);
      const identityKey = buildSourceIdentityKey(file, href);

      if (
        !fromSource &&
        !href &&
        filesWithSourceMetadata.has(normalizedFileName)
      ) {
        return;
      }

      const existing = itemsByIdentity.get(identityKey);
      if (existing) {
        if (!existing.href && href) existing.href = href;
        if (page) existing.pages.add(page);
        return;
      }

      if (fromSource) filesWithSourceMetadata.add(normalizedFileName);

      const pages = new Set<string>();
      if (page) pages.add(page);
      itemsByIdentity.set(identityKey, { identityKey, file, href, pages });
    };

    sources.forEach((source: KnowledgeSourcePayload) => {
      const meta = source.metadata;
      if (!meta) return;
      const metadata = meta;
      const fileName = (metadata.file_name ||
        metadata.filename ||
        metadata.source ||
        metadata.name) as string | undefined;
      const page =
        metadata.page_label ?? metadata.page ?? metadata.page_number;
      const href = resolveSourceUrl(
        metadata,
        source as unknown as Record<string, unknown>,
      );
      register({
        fileRaw: fileName,
        pageRaw: page,
        hrefRaw: href,
        fromSource: true,
      });
    });

    files.forEach((file) => register({ fileRaw: file, fromSource: false }));

    projectResults.forEach((entry) =>
      register({ fileRaw: entry?.filename, fromSource: false }),
    );

    return Array.from(itemsByIdentity.values()).map((item) => ({
      key: item.identityKey,
      label: item.file,
      href: item.href,
      secondary: buildPageSummary(item.pages, "short"),
      leading: <FileTypeBadge filename={item.file} />,
    }));
  }, [files, projectResults, sources]);

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="rounded-lg border border-border/60 bg-card overflow-hidden">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="group flex h-auto w-full items-center justify-start gap-2 border-0 bg-transparent px-3 py-2 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted/50"
        aria-expanded={expanded}
      >
        <BookOpen
          className={cn(
            "h-4 w-4",
            result ? ICON_COLOR : "text-muted-foreground",
          )}
        />
        <span className="flex-1 type-size-14 font-medium truncate">
          {getToolDisplayName(part.toolName)}: {query || "search"}
        </span>
        <span className="type-size-12 text-muted-foreground">
          {sourceCount} results
        </span>
        <CaretRight
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform group-hover:text-foreground",
            expanded && "rotate-90",
          )}
        />
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

          {/* Sources (primary content) */}
          <SourceList items={sourceItems} />

          {/* Retrieved content (secondary) */}
          <ContentDisclosure content={rawContent} />

          {/* Error */}
          {result?.error && (
            <div className="type-size-14 text-destructive">{result.error}</div>
          )}
        </div>
      )}
    </div>
  );
};
