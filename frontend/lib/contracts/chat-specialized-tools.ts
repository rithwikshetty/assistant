import {
  type JsonRecord,
  expectRecord,
  readNullableString,
  readNullableBoolean,
  readNullableNumber,
  readNullableStringArray,
} from "./contract-utils";

export interface FileReadChunkPayload {
  content?: string | null;
  chunk_start?: number | null;
  chunk_end?: number | null;
}

export interface FileReadContentBlockPayload {
  type?: string | null;
  text?: string | null;
  source?: JsonRecord | null;
}

export interface FileReadResultPayload {
  file_id?: string | null;
  filename?: string | null;
  original_filename?: string | null;
  file_type?: string | null;
  chunks?: FileReadChunkPayload[] | null;
  total_length?: number | null;
  has_more?: boolean | null;
  is_truncated?: boolean | null;
  content?: string | null;
  note?: string | null;
  has_embedded_images?: boolean | null;
  embedded_image_count?: number | null;
  _content_blocks?: FileReadContentBlockPayload[] | null;
  error?: string | null;
}

export interface ExecuteCodeGeneratedFilePayload {
  file_id?: string | null;
  filename?: string | null;
  file_type?: string | null;
  file_size?: number | null;
  download_url?: string | null;
  download_path?: string | null;
}

export interface ExecuteCodeResultPayload {
  code?: string | null;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  execution_time_ms?: number | null;
  success?: boolean | null;
  error?: string | null;
  generated_files?: ExecuteCodeGeneratedFilePayload[] | null;
  retries_used?: number | null;
}

export interface SkillResultPayload {
  skill_id?: string | null;
  title?: string | null;
  name?: string | null;
  content?: string | null;
  is_module?: boolean | null;
  has_modules?: boolean | null;
  available_modules?: string[] | null;
  parent_skill?: string | null;
  note?: string | null;
  error?: string | null;
  message?: string | null;
}

export type SpecializedToolResultPayload =
  | FileReadResultPayload
  | ExecuteCodeResultPayload
  | SkillResultPayload;

export function parseFileReadResultPayload(
  raw: unknown,
  label: string = "fileReadResult",
): FileReadResultPayload {
  const record = expectRecord(raw, label);
  return {
    file_id: readNullableString(record, "file_id"),
    filename: readNullableString(record, "filename"),
    original_filename: readNullableString(record, "original_filename"),
    file_type: readNullableString(record, "file_type"),
    chunks: (() => {
      if (!("chunks" in record)) return undefined;
      const rawChunks = record.chunks;
      if (rawChunks == null) return null;
      if (!Array.isArray(rawChunks)) {
        throw new Error(`${label}.chunks must be an array or null`);
      }
      return rawChunks.map((entry, index) => {
        const chunk = expectRecord(entry, `${label}.chunks[${index}]`);
        return {
          content: readNullableString(chunk, "content"),
          chunk_start: readNullableNumber(chunk, "chunk_start"),
          chunk_end: readNullableNumber(chunk, "chunk_end"),
        };
      });
    })(),
    total_length: readNullableNumber(record, "total_length"),
    has_more: readNullableBoolean(record, "has_more"),
    is_truncated: readNullableBoolean(record, "is_truncated"),
    content: readNullableString(record, "content"),
    note: readNullableString(record, "note"),
    has_embedded_images: readNullableBoolean(record, "has_embedded_images"),
    embedded_image_count: readNullableNumber(record, "embedded_image_count"),
    _content_blocks: (() => {
      if (!("_content_blocks" in record)) return undefined;
      const rawBlocks = record._content_blocks;
      if (rawBlocks == null) return null;
      if (!Array.isArray(rawBlocks)) {
        throw new Error(`${label}._content_blocks must be an array or null`);
      }
      return rawBlocks.map((entry, index) => {
        const block = expectRecord(entry, `${label}._content_blocks[${index}]`);
        return {
          type: readNullableString(block, "type"),
          text: readNullableString(block, "text"),
          source: (() => {
            if (!("source" in block)) return undefined;
            const source = block.source;
            if (source == null) return null;
            return expectRecord(source, `${label}._content_blocks[${index}].source`);
          })(),
        };
      });
    })(),
    error: readNullableString(record, "error"),
  };
}

export function parseExecuteCodeResultPayload(
  raw: unknown,
  label: string = "executeCodeResult",
): ExecuteCodeResultPayload {
  const record = expectRecord(raw, label);
  return {
    code: readNullableString(record, "code"),
    stdout: readNullableString(record, "stdout"),
    stderr: readNullableString(record, "stderr"),
    exit_code: readNullableNumber(record, "exit_code"),
    execution_time_ms: readNullableNumber(record, "execution_time_ms"),
    success: readNullableBoolean(record, "success"),
    error: readNullableString(record, "error"),
    generated_files: (() => {
      if (!("generated_files" in record)) return undefined;
      const rawFiles = record.generated_files;
      if (rawFiles == null) return null;
      if (!Array.isArray(rawFiles)) {
        throw new Error(`${label}.generated_files must be an array or null`);
      }
      return rawFiles.map((entry, index) => {
        const file = expectRecord(entry, `${label}.generated_files[${index}]`);
        return {
          file_id: readNullableString(file, "file_id"),
          filename: readNullableString(file, "filename"),
          file_type: readNullableString(file, "file_type"),
          file_size: readNullableNumber(file, "file_size"),
          download_url: readNullableString(file, "download_url"),
          download_path: readNullableString(file, "download_path"),
        };
      });
    })(),
    retries_used: readNullableNumber(record, "retries_used"),
  };
}

export function parseSkillResultPayload(
  raw: unknown,
  label: string = "skillResult",
): SkillResultPayload {
  const record = expectRecord(raw, label);
  return {
    skill_id: readNullableString(record, "skill_id"),
    title: readNullableString(record, "title"),
    name: readNullableString(record, "name"),
    content: readNullableString(record, "content"),
    is_module: readNullableBoolean(record, "is_module"),
    has_modules: readNullableBoolean(record, "has_modules"),
    available_modules: readNullableStringArray(record, "available_modules"),
    parent_skill: readNullableString(record, "parent_skill"),
    note: readNullableString(record, "note"),
    error: readNullableString(record, "error"),
    message: readNullableString(record, "message"),
  };
}
