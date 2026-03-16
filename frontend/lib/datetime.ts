const ISO_WITHOUT_TZ_REGEX = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;
const ISO_WITH_TZ_REGEX = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i;
const DATE_ONLY_REGEX = /^\d{4}-\d{2}-\d{2}$/;

function parseDateOnlyParts(value: string): { year: number; month: number; day: number } | null {
  if (!DATE_ONLY_REGEX.test(value)) return null;
  const [yearRaw, monthRaw, dayRaw] = value.split("-");
  const year = Number(yearRaw);
  const month = Number(monthRaw);
  const day = Number(dayRaw);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return null;
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }
  return { year, month, day };
}

/**
 * Normalize API timestamps so that naive datetimes (without an explicit offset)
 * are treated as UTC instead of being interpreted in the user's local timezone.
 */
export function normalizeBackendTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;

  const normalizedSeparator = trimmed.includes(" ") ? trimmed.replace(" ", "T") : trimmed;

  if (ISO_WITH_TZ_REGEX.test(normalizedSeparator)) {
    return normalizedSeparator;
  }

  if (ISO_WITHOUT_TZ_REGEX.test(normalizedSeparator)) {
    return `${normalizedSeparator}Z`;
  }

  return normalizedSeparator;
}

export function parseBackendDate(value: string | null | undefined): Date | null {
  const normalized = normalizeBackendTimestamp(value);
  if (!normalized) return null;
  const ms = Date.parse(normalized);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms);
}

export function parseBackendDateOnly(value: string | null | undefined): Date | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parts = parseDateOnlyParts(trimmed);
  if (!parts) return null;
  const localDate = new Date(parts.year, parts.month - 1, parts.day);
  if (
    localDate.getFullYear() !== parts.year
    || localDate.getMonth() !== parts.month - 1
    || localDate.getDate() !== parts.day
  ) {
    return null;
  }
  return localDate;
}

export function dateOnlyToEpochMs(value: string | null | undefined): number {
  const parsed = parseBackendDateOnly(value);
  return parsed ? parsed.getTime() : Number.NaN;
}

export function daysBetweenDateOnlyInclusive(startDate: string, endDate: string): number {
  const start = parseDateOnlyParts(startDate);
  const end = parseDateOnlyParts(endDate);
  if (!start || !end) return 1;

  const startUtc = Date.UTC(start.year, start.month - 1, start.day);
  const endUtc = Date.UTC(end.year, end.month - 1, end.day);
  const diff = Math.floor((endUtc - startUtc) / 86400000);
  return Math.max(1, diff + 1);
}

/**
 * Compact relative time for sidebar rows: "2m", "9h", "1d", "3w", "2mo"
 */
export function formatRelativeCompact(isoTimestamp: string | null | undefined): string | null {
  const parsed = parseBackendDate(isoTimestamp);
  if (!parsed) return null;
  const diffMs = Date.now() - parsed.getTime();
  if (diffMs <= 0) return "now";
  const diffMinutes = Math.round(diffMs / 60000);
  if (diffMinutes < 1) return "now";
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d`;
  const diffWeeks = Math.round(diffDays / 7);
  if (diffWeeks < 5) return `${diffWeeks}w`;
  const diffMonths = Math.round(diffDays / 30);
  if (diffMonths < 12) return `${diffMonths}mo`;
  const diffYears = Math.round(diffDays / 365);
  return `${diffYears}y`;
}

export function formatRelativeLabel(isoTimestamp: string | null | undefined): string | null {
  const parsed = parseBackendDate(isoTimestamp);
  if (!parsed) return null;
  const diffMs = Date.now() - parsed.getTime();
  if (diffMs <= 0) return "Just now";
  const diffMinutes = Math.round(diffMs / 60000);
  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) {
    return `${diffMinutes} min ago`;
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours} hr${diffHours === 1 ? "" : "s"} ago`;
  }
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
}
