/**
 * Shared parsing utilities for contract modules.
 *
 * Every contract file needs the same low-level readers for
 * unknown → typed field extraction.  They live here once.
 */

export type JsonRecord = Record<string, unknown>;

export function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function expectRecord(value: unknown, label: string): JsonRecord {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value;
}

export function readString(record: JsonRecord, key: string, label: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label}.${key} must be a non-empty string`);
  }
  return value;
}

export function readBoolean(record: JsonRecord, key: string, label: string): boolean {
  if (typeof record[key] !== "boolean") {
    throw new Error(`${label}.${key} must be a boolean`);
  }
  return record[key] as boolean;
}

function formatKey(key: string, label?: string): string {
  return label ? `${label}.${key}` : key;
}

export function readNullableString(
  record: JsonRecord,
  key: string,
  label?: string,
): string | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  if (typeof value !== "string") {
    throw new Error(`${formatKey(key, label)} must be a string or null`);
  }
  return value;
}

export function readNullableBoolean(
  record: JsonRecord,
  key: string,
  label?: string,
): boolean | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  if (typeof value !== "boolean") {
    throw new Error(`${formatKey(key, label)} must be a boolean or null`);
  }
  return value;
}

export function readNullableNumber(
  record: JsonRecord,
  key: string,
  label?: string,
): number | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${formatKey(key, label)} must be a finite number or null`);
  }
  return value;
}

export function readNullableStringArray(
  record: JsonRecord,
  key: string,
  label?: string,
): string[] | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  if (!Array.isArray(value)) {
    throw new Error(`${formatKey(key, label)} must be an array or null`);
  }
  return value.map((entry, index) => {
    if (typeof entry !== "string") {
      throw new Error(`${formatKey(key, label)}[${index}] must be a string`);
    }
    return entry;
  });
}

export function readNullableRecord(
  record: JsonRecord,
  key: string,
): JsonRecord | null | undefined {
  if (!(key in record)) return undefined;
  const value = record[key];
  if (value == null) return null;
  return expectRecord(value, key);
}

export function readRecordArray(
  record: JsonRecord,
  key: string,
  label: string,
): JsonRecord[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw new Error(`${label}.${key} must be an array`);
  }
  return value.map((entry, index) => expectRecord(entry, `${label}.${key}[${index}]`));
}

export function readNullableEnumString<const T extends readonly string[]>(
  record: JsonRecord,
  key: string,
  label: string,
  allowedValues: T,
): T[number] | null | undefined {
  const value = readNullableString(record, key, label);
  if (value == null) return value;
  if ((allowedValues as readonly string[]).includes(value)) {
    return value as T[number];
  }
  throw new Error(`${label}.${key} must be one of: ${allowedValues.join(", ")}`);
}

/**
 * Generic safe-parse wrapper. Returns `null` on parse failure instead of throwing.
 * Use this in display components to gracefully handle unexpected payloads.
 */
export function tryParse<T>(
  raw: unknown,
  parser: (value: unknown, label: string) => T,
  label: string,
): T | null {
  if (raw == null) return null;
  try {
    return parser(raw, label);
  } catch {
    return null;
  }
}
