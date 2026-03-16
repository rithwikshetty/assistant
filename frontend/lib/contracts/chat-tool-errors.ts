import {
  expectRecord,
  readNullableString,
} from "./contract-utils";

export interface ToolErrorPayload {
  message?: string | null;
  code?: string | null;
}

export function parseToolErrorPayload(
  raw: unknown,
  label: string = "toolError",
): ToolErrorPayload {
  const record = expectRecord(raw, label);
  return {
    message: readNullableString(record, "message", label),
    code: readNullableString(record, "code", label),
  };
}
