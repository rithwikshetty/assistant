const safeString = (value: unknown): string => {
  if (typeof value === "string" && value.trim().length > 0) {
    return value.trim();
  }
  return "";
};

const URL_FIELDS = [
  "web_url", "source_url", "url", "href", "link",
  "document_url", "file_url", "sharepoint_url",
] as const;

const getUrlFromRecord = (record?: Record<string, unknown>): string => {
  if (!record) return "";
  for (const field of URL_FIELDS) {
    const value = safeString(record[field]);
    if (value) return value;
  }
  return "";
};

export const resolveSourceUrl = (
  metadata: Record<string, unknown>,
  source?: Record<string, unknown>,
): string => {
  return getUrlFromRecord(metadata) || getUrlFromRecord(source);
};

export const normalizePageLabel = (value: unknown): string | undefined => {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return value.toString();
  return undefined;
};

const orderedPageLabels = (labels: Iterable<string>): string[] => {
  const normalized = Array.from(
    new Set(
      Array.from(labels)
        .map((value) => value.trim())
        .filter((value) => value.length > 0),
    ),
  );
  if (normalized.length === 0) return [];

  const numeric = normalized.filter((value) => /^\d+$/.test(value)).sort((a, b) => Number(a) - Number(b));
  const nonNumeric = normalized.filter((value) => !/^\d+$/.test(value)).sort((a, b) => a.localeCompare(b));
  return [...numeric, ...nonNumeric];
};

export const buildPageSummary = (pages: Set<string>, style: "short" | "long" = "long"): string | undefined => {
  const ordered = orderedPageLabels(pages);
  if (ordered.length === 0) return undefined;

  if (style === "short") {
    if (ordered.length === 1) return `p. ${ordered[0]}`;
    return `pp. ${ordered.join(", ")}`;
  }

  if (ordered.length === 1) return `Page ${ordered[0]}`;
  return `Pages ${ordered.join(", ")}`;
};

export const buildSourceIdentityKey = (fileName: string, href?: string): string => {
  const normalizedFile = fileName.trim().toLowerCase();
  const normalizedHref = safeString(href);
  return `${normalizedFile}|${normalizedHref}`;
};
