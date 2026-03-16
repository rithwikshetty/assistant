export function normalizeNonEmptyString(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const normalized = raw.trim();
  return normalized.length > 0 ? normalized : null;
}
