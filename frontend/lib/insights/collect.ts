// Shared collector for message insights (sources). Parses a message once and
// returns grouped entries, total count, and rates metadata.
// UI layers (icons/labels) stay outside this module.

import { TOOL, isKnowledgeToolName } from "@/lib/tools/constants";
import {
  buildPageSummary,
  buildSourceIdentityKey,
  normalizePageLabel,
  resolveSourceUrl,
} from "@/lib/insights/source-normalization";

export type InsightCategory =
  | "web"
  | "knowledge" // fallback for uncategorized knowledge entries
  | "project"
  | "other";

export type MessageInsightEntry = {
  id: string;
  category: InsightCategory;
  primary: string;
  secondary?: string;
  href?: string;
  description?: string;
  badge?: string;
  toolName?: string;
};

export type InsightGroup = {
  category: InsightCategory;
  entries: MessageInsightEntry[];
};

export type RateInsightItem = {
  id: string;
  description: string;
  rate?: number | null;
  uom?: string | null;
  location?: string | null;
  sector?: string | null;
  base_date?: string | null;
  key_rate?: string | null;
  category?: string | null;
  nrm_element?: string | null;
};

export type BcisIndexInsightItem = {
  id: string;
  indexType: "location" | "inflation" | "labour";
  label: string; // for display (e.g., location name, date)
  value?: number | null; // single value for location/labour
  // For inflation type, we'll store the breakdown
  material_cost_index?: number | null;
  labour_cost_index?: number | null;
  plant_cost_index?: number | null;
  building_cost_index?: number | null;
  tender_price_index?: number | null;
};

export type ProjectDetailsInsightItem = {
  id: string;
  name: string; // file_name or project_code
  project_code?: string | null;
  location?: string | null;
  sector?: string | null;
  primary_use?: string | null;
  base_quarter?: string | null;
  base_date?: string | null;
  gia?: number | null;
};

export type CollectedInsights = {
  groups: InsightGroup[];
  total: number;
  hasRates: boolean;
  ratesCount: number;
  rates: RateInsightItem[];
  bcisIndices: BcisIndexInsightItem[];
  projectDetails: ProjectDetailsInsightItem[];
};

const INSIGHT_ORDER: InsightCategory[] = [
  "web",
  "knowledge",
  "project",
  "other",
];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const safeString = (value: unknown): string => {
  if (typeof value === "string" && value.trim().length > 0) {
    return value.trim();
  }
  return "";
};

const safeNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const mergedSourceMetadata = (source: Record<string, unknown>): Record<string, unknown> => {
  const metadata = isRecord(source.metadata) ? source.metadata : {};
  const extraInfo = isRecord(source.extra_info) ? source.extra_info : {};
  return { ...extraInfo, ...metadata };
};

const getHostFromUrl = (value?: string): string | undefined => {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.host.replace(/^www\./i, "");
  } catch {
    return undefined;
  }
};

const buildEntryKey = (entry: MessageInsightEntry): string => {
  const href = entry.href ? entry.href.toLowerCase() : "";
  const primary = entry.primary.toLowerCase();
  const secondary = entry.secondary ? entry.secondary.toLowerCase() : "";
  const badge = entry.badge ? entry.badge.toLowerCase() : "";
  return `${entry.category}|${href}|${primary}|${secondary}|${badge}`;
};

const extractWebEntries = (
  toolCallId: string,
  toolName: string | undefined,
  result: Record<string, unknown>,
): MessageInsightEntry[] => {
  const citationsRaw = result.citations;
  const citations = Array.isArray(citationsRaw) ? citationsRaw : [];
  const entries: MessageInsightEntry[] = [];

  citations.forEach((citation, index) => {
    if (!isRecord(citation)) return;
    const url = safeString(citation.url);
    const title = safeString(citation.title);
    const snippet = safeString(citation.snippet);
    const citationIndex = safeNumber(citation.index);
    const host = getHostFromUrl(url);

    if (!url && !title) return;

    entries.push({
      id: `${toolCallId}-web-${index}`,
      category: "web",
      primary: title || host || url || `Result ${index + 1}`,
      secondary: host && host !== title ? host : undefined,
      href: url || undefined,
      description: snippet || undefined,
      badge: citationIndex !== null ? citationIndex.toString() : undefined,
      toolName,
    });
  });

  return entries;
};

const normalizeKnowledgeEntry = ({
  toolCallId,
  toolName,
  identityKey,
  fileName,
  secondary,
  url,
  description,
}: {
  toolCallId: string;
  toolName?: string;
  identityKey: string;
  fileName: string;
  secondary?: string;
  url?: string;
  description?: string;
}): MessageInsightEntry => {
  return {
    id: `${toolCallId}-kb-${identityKey}`,
    category: "knowledge",
    primary: fileName,
    secondary,
    href: url,
    description,
    toolName,
  };
};

const extractKnowledgeEntries = (
  toolCallId: string,
  toolName: string | undefined,
  result: Record<string, unknown>,
): MessageInsightEntry[] => {
  const entriesByIdentity = new Map<
    string,
    {
      identityKey: string;
      fileName: string;
      href?: string;
      description?: string;
      pages: Set<string>;
    }
  >();
  const filesWithSourceMetadata = new Set<string>();

  const register = ({
    fileNameRaw,
    pageRaw,
    urlRaw,
    descriptionRaw,
    fromSource,
  }: {
    fileNameRaw: unknown;
    pageRaw?: unknown;
    urlRaw?: unknown;
    descriptionRaw?: unknown;
    fromSource?: boolean;
  }) => {
    const fileName = safeString(fileNameRaw);
    if (!fileName) return;

    const normalizedFileName = fileName.toLowerCase();
    const page = normalizePageLabel(pageRaw);
    const url = safeString(urlRaw);
    const description = safeString(descriptionRaw);
    const identityKey = buildSourceIdentityKey(fileName, url || undefined);

    if (!fromSource && !url && filesWithSourceMetadata.has(normalizedFileName)) {
      return;
    }

    const existing = entriesByIdentity.get(identityKey);
    if (existing) {
      if (page) {
        existing.pages.add(page);
      }
      if (!existing.href && url) {
        existing.href = url;
      }
      if (!existing.description && description) {
        existing.description = description;
      }
      return;
    }

    if (fromSource) {
      filesWithSourceMetadata.add(normalizedFileName);
    }

    const pages = new Set<string>();
    if (page) {
      pages.add(page);
    }
    entriesByIdentity.set(identityKey, {
      identityKey,
      fileName,
      href: url || undefined,
      description: description || undefined,
      pages,
    });
  };

  const sourcesRaw = result.sources;
  if (Array.isArray(sourcesRaw)) {
    sourcesRaw.forEach((source) => {
      if (!isRecord(source)) return;
      const metadata = mergedSourceMetadata(source);
      const fileName =
        metadata.file_name ?? metadata.fileName ?? metadata.filename ?? metadata.source ?? source.file ?? source.name;
      const page = metadata.page_label ?? metadata.page ?? metadata.page_number ?? source.page;
      const url = resolveSourceUrl(metadata, source);
      const description = safeString(metadata.summary ?? metadata.description ?? source.summary ?? source.description);
      register({
        fileNameRaw: fileName,
        pageRaw: page,
        urlRaw: url,
        descriptionRaw: description,
        fromSource: true,
      });
    });
  }

  const filesRaw = result.files;
  if (Array.isArray(filesRaw)) {
    filesRaw.forEach((entry) => register({ fileNameRaw: entry, fromSource: false }));
  }

  return Array.from(entriesByIdentity.values()).map((entry) =>
    normalizeKnowledgeEntry({
      toolCallId,
      toolName,
      identityKey: entry.identityKey,
      fileName: entry.fileName,
      secondary: buildPageSummary(entry.pages, "long"),
      url: entry.href,
      description: entry.description,
    }),
  );
};

const extractProjectFileEntries = (
  toolCallId: string,
  toolName: string | undefined,
  args: unknown,
  result: Record<string, unknown>,
): MessageInsightEntry[] => {
  const entries: MessageInsightEntry[] = [];

  const fileNameCandidates = [result.original_filename, result.filename, result.file_name];

  if (Array.isArray(result.chunks)) {
    result.chunks.forEach((chunk) => {
      if (!isRecord(chunk)) return;
      fileNameCandidates.push(chunk.original_filename, chunk.filename);
    });
  }

  const fileName = fileNameCandidates.map(safeString).find((candidate) => candidate.length > 0);
  const fallbackFileId = isRecord(args) ? safeString((args as Record<string, unknown>).file_id) : "";

  const primary = fileName || fallbackFileId;
  if (!primary) {
    return entries;
  }

  const chunkCount = Array.isArray(result.chunks) ? result.chunks.length : null;
  const badge = chunkCount && chunkCount > 1 ? `${chunkCount} ranges` : undefined;

  entries.push({
    id: `${toolCallId}-project-${primary}`,
    category: "project",
    primary,
    secondary: chunkCount && chunkCount > 0 ? `${chunkCount} range${chunkCount === 1 ? "" : "s"}` : undefined,
    badge,
    toolName,
  });

  return entries;
};

const extractGenericEntries = (
  toolCallId: string,
  toolName: string | undefined,
  result: Record<string, unknown>,
): MessageInsightEntry[] => {
  const entries: MessageInsightEntry[] = [];

  const citationsRaw = result.citations;
  if (Array.isArray(citationsRaw)) {
    citationsRaw.forEach((citation, index) => {
      if (!isRecord(citation)) return;
      const url = safeString(citation.url);
      const title = safeString(citation.title);
      if (!url && !title) return;

      entries.push({
        id: `${toolCallId}-generic-citation-${index}`,
        category: url ? "web" : "other",
        primary: title || url,
        href: url || undefined,
        toolName,
      });
    });
  }

  const sourcesRaw = result.sources;
  if (Array.isArray(sourcesRaw)) {
    sourcesRaw.forEach((source, index) => {
      if (!isRecord(source)) return;
      const metadata = mergedSourceMetadata(source);
      const title = safeString(source.title ?? source.name ?? metadata.file_name ?? metadata.title);
      const url = resolveSourceUrl(metadata, source);
      const description = safeString(source.description ?? source.summary ?? metadata.description ?? metadata.summary);
      if (!title && !url) return;

      entries.push({
        id: `${toolCallId}-generic-source-${index}`,
        category: url ? "web" : "other",
        primary: title || url,
        href: url || undefined,
        description: description || undefined,
        toolName,
      });
    });
  }

  const filesRaw = result.files;
  if (Array.isArray(filesRaw)) {
    filesRaw.forEach((file, index) => {
      const fileName = safeString(file);
      if (!fileName) return;
      entries.push({
        id: `${toolCallId}-generic-file-${index}`,
        category: "other",
        primary: fileName,
        toolName,
      });
    });
  }

  return entries;
};

const extractInsightsFromPart = (part: Record<string, unknown>, index: number): MessageInsightEntry[] => {
  const type = safeString(part.type);
  if (type !== "tool-call") return [];

  const toolNameRaw = part.toolName;
  const toolName = typeof toolNameRaw === "string" ? toolNameRaw : undefined;
  const toolCallIdRaw = (part as { toolCallId?: unknown; id?: unknown }).toolCallId ?? (part as { id?: unknown }).id;
  const toolCallId =
    typeof toolCallIdRaw === "string" && toolCallIdRaw.trim().length > 0 ? toolCallIdRaw.trim() : `tool-${index}`;
  const resultRaw = (part as { result?: unknown }).result as unknown;
  if (!isRecord(resultRaw)) {
    // Non-object results are not rendered in insights.
    return [];
  }

  const args = (part as { args?: unknown }).args;

  if (toolName === TOOL.WEB_SEARCH) {
    return extractWebEntries(toolCallId, toolName, resultRaw);
  }

  if (isKnowledgeToolName(toolName)) {
    return extractKnowledgeEntries(toolCallId, toolName, resultRaw);
  }

  if (toolName === TOOL.FILE_READER) {
    return extractProjectFileEntries(toolCallId, toolName, args, resultRaw);
  }

  return extractGenericEntries(toolCallId, toolName, resultRaw);
};

export const collectMessageInsights = (message: unknown): CollectedInsights => {
  if (!isRecord(message)) {
    return { groups: [], total: 0, hasRates: false, ratesCount: 0, rates: [], bcisIndices: [], projectDetails: [] };
  }

  const contentRaw = (message as { content?: unknown }).content;
  const content = Array.isArray(contentRaw) ? contentRaw : [];

  const seen = new Set<string>();
  const grouped = new Map<InsightCategory, MessageInsightEntry[]>();
  const ratesSeen = new Set<string>();
  const ratesCollected: RateInsightItem[] = [];
  const bcisIndicesCollected: BcisIndexInsightItem[] = [];
  const projectDetailsCollected: ProjectDetailsInsightItem[] = [];
  let hasRates = false;
  let ratesCount = 0;

  content.forEach((part, index) => {
    if (!isRecord(part)) return;

    // Detect rates usage, count, and extract rate items in the same pass
    const type = safeString(part.type);
    if (type === "tool-call") {
      const toolCallId = typeof part.toolCallId === "string" ? part.toolCallId : `tool-${index}`;
      const result = (part as { result?: unknown }).result;

      // Extract rates from array result
      if (Array.isArray(result)) {
        result.forEach((item, idx) => {
          if (!isRecord(item)) return;
          if (typeof item.description === "string" || typeof item.rate === "number") {
            hasRates = true;
            ratesCount++;

            const description = safeString(item.description);
            if (!description) return;

            const dedupeKey = `${description}|${item.rate}|${item.location}`;
            if (ratesSeen.has(dedupeKey)) return;
            ratesSeen.add(dedupeKey);

            ratesCollected.push({
              id: `${toolCallId}-rate-${idx}`,
              description,
              rate: typeof item.rate === "number" ? item.rate : null,
              uom: safeString(item.uom) || null,
              location: safeString(item.location) || null,
              sector: safeString(item.sector) || null,
              base_date: safeString(item.base_date) || null,
              key_rate: safeString(item.key_rate) || null,
              category: safeString(item.category) || null,
              nrm_element: safeString(item.nrm_element) || null,
            });
          }
        });
      } else if (isRecord(result) && Array.isArray((result as { rates?: unknown[] }).rates)) {
        hasRates = true;
        const ratesArray = (result as { rates: unknown[] }).rates;
        ratesCount += ratesArray.length;

        ratesArray.forEach((item, idx) => {
          if (!isRecord(item)) return;

          const description = safeString(item.description);
          if (!description) return;

          const dedupeKey = `${description}|${item.rate}|${item.location}`;
          if (ratesSeen.has(dedupeKey)) return;
          ratesSeen.add(dedupeKey);

          ratesCollected.push({
            id: `${toolCallId}-rate-${idx}`,
            description,
            rate: typeof item.rate === "number" ? item.rate : null,
            uom: safeString(item.uom) || null,
            location: safeString(item.location) || null,
            sector: safeString(item.sector) || null,
            base_date: safeString(item.base_date) || null,
            key_rate: safeString(item.key_rate) || null,
            category: safeString(item.category) || null,
            nrm_element: safeString(item.nrm_element) || null,
          });
        });
      }

    }

    const entries = extractInsightsFromPart(part, index);
    entries.forEach((entry) => {
      if (!entry.primary) return;
      const dedupeKey = buildEntryKey(entry);
      if (seen.has(dedupeKey)) return;
      seen.add(dedupeKey);

      const bucket = grouped.get(entry.category);
      if (bucket) {
        bucket.push(entry);
      } else {
        grouped.set(entry.category, [entry]);
      }
    });
  });

  const groups = INSIGHT_ORDER.map((category) => {
    const entries = grouped.get(category);
    if (!entries || entries.length === 0) return null;
    return { category, entries } as InsightGroup;
  }).filter((g): g is InsightGroup => Boolean(g));

  const total = Array.from(grouped.values()).reduce((acc, list) => acc + list.length, 0);

  return {
    groups,
    total,
    hasRates,
    ratesCount,
    rates: ratesCollected,
    bcisIndices: bcisIndicesCollected,
    projectDetails: projectDetailsCollected,
  };
};
