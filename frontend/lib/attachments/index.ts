export type FileAttachmentMeta = {
  id: string;
  filename?: string;
  original_filename?: string;
  file_type?: string;
  file_size?: number;
  uploaded_at?: string | null;
  checksum?: string | null;
  redaction_requested?: boolean;
  redaction_applied?: boolean;
  redacted_categories?: string[];
  extracted_text?: string | null;
};

export const FILE_REFERENCE_SCHEMA = "assist.file-reference.v1" as const;
export const FILE_REFERENCE_MIME = "application/json+assist" as const;

export const createFileReferencePart = (meta: FileAttachmentMeta) => ({
  type: "file" as const,
  data: JSON.stringify({ schema: FILE_REFERENCE_SCHEMA, ...meta }),
  mimeType: FILE_REFERENCE_MIME,
});

export function extractFileAttachmentMeta(
  attachment: { meta?: unknown; content?: unknown[] } | null | undefined
): FileAttachmentMeta | undefined {
  try {
    const meta = (attachment as { meta?: Record<string, unknown> } | undefined)?.meta;
    if (meta && typeof (meta as { id?: unknown }).id === "string") {
      return meta as FileAttachmentMeta;
    }
    const parts = Array.isArray((attachment as { content?: unknown[] } | undefined)?.content)
      ? ((attachment as { content?: unknown[] }).content as unknown[])
      : [];
    for (const part of parts) {
      if (
        part &&
        typeof part === "object" &&
        (part as { type?: string }).type === "file" &&
        (part as { mimeType?: string }).mimeType === FILE_REFERENCE_MIME
      ) {
        try {
          const data = JSON.parse((part as { data?: string }).data ?? "{}");
          if (data && typeof data === "object" && typeof (data as { id?: unknown }).id === "string") {
            return data as FileAttachmentMeta;
          }
        } catch {
          // ignore
        }
      }
    }
  } catch {
    // ignore
  }
  return undefined;
}

export function formatBytes(size?: number): string {
  if (!size || Number.isNaN(size)) return "";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"] as const;
  let value = size / 1024;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[idx]}`;
}

// Dev-only helper tests: not executed automatically. Import and call manually if desired.
export function runAttachmentHelpersSelfTest() {
  const results: Record<string, boolean> = {};

  // formatBytes cases
  results["formatBytes_0"] = formatBytes(0) === "";
  results["formatBytes_999"] = formatBytes(999) === "999 B";
  results["formatBytes_1024"] = formatBytes(1024) === "1.0 KB";
  results["formatBytes_1048576"] = formatBytes(1024 * 1024) === "1.0 MB";

  // extractFileAttachmentMeta cases
  const meta: FileAttachmentMeta = {
    id: "test-id",
    filename: "sys.pdf",
    original_filename: "orig.pdf",
    file_type: "application/pdf",
    file_size: 1234,
  };
  const attWithMeta = { meta };
  const attWithPart = {
    content: [
      {
        type: "file",
        mimeType: FILE_REFERENCE_MIME,
        data: JSON.stringify({ schema: FILE_REFERENCE_SCHEMA, ...meta }),
      },
    ],
  };
  const parsed1 = extractFileAttachmentMeta(attWithMeta);
  const parsed2 = extractFileAttachmentMeta(attWithPart);
  results["extract_meta_property"] = !!parsed1 && parsed1.id === meta.id && parsed1.original_filename === meta.original_filename;
  results["extract_meta_part"] = !!parsed2 && parsed2.id === meta.id && parsed2.file_type === meta.file_type;

  const ok = Object.values(results).every(Boolean);
  return { ok, results };
}
