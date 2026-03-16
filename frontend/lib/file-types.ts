/**
 * Centralized file type configuration matching backend support.
 * Keep in sync with backend/app/config/file_types.py
 *
 * LlamaParse supports 70+ file formats:
 * https://developers.llamaindex.ai/python/cloud/llamaparse/features/supported_document_types/
 */

// Document formats
export const DOCUMENT_EXTENSIONS = [
  "pdf",
  "doc",
  "docx",
  "docm",
  "dot",
  "dotm",
  "rtf",
  "pages",
  "epub",
  "602",
  "abw",
  "cwk",
  "hwp",
  "lwp",
  "mw",
  "mcw",
  "pbd",
  "wpd",
  "wps",
  "sda",
  "sdw",
  "sgl",
  "stw",
  "sxw",
  "sxg",
  "uof",
  "uot",
  "vor",
  "zabw",
] as const;

// Presentation formats
export const PRESENTATION_EXTENSIONS = [
  "ppt",
  "pptx",
  "pptm",
  "pot",
  "potm",
  "potx",
  "key",
  "sdd",
  "sdp",
  "sti",
  "sxi",
] as const;

// Spreadsheet formats
export const SPREADSHEET_EXTENSIONS = [
  "xlsx",
  "xls",
  "xlsm",
  "xlsb",
  "xlw",
  "csv",
  "numbers",
  "ods",
  "fods",
  "dif",
  "sylk",
  "slk",
  "prn",
  "et",
  "uos1",
  "uos2",
  "dbf",
  "wk1",
  "wk2",
  "wk3",
  "wk4",
  "wks",
  "123",
  "wq1",
  "wq2",
  "wb1",
  "wb2",
  "wb3",
  "qpw",
  "xlr",
  "eth",
  "tsv",
] as const;

// Image formats
export const IMAGE_EXTENSIONS = [
  "jpg",
  "jpeg",
  "png",
] as const;

// Web formats
export const WEB_EXTENSIONS = ["html", "htm", "web", "xml"] as const;

// Text formats
export const TEXT_EXTENSIONS = ["txt", "cgm"] as const;

// All supported extensions combined
export const ALL_EXTENSIONS = [
  ...DOCUMENT_EXTENSIONS,
  ...PRESENTATION_EXTENSIONS,
  ...SPREADSHEET_EXTENSIONS,
  ...IMAGE_EXTENSIONS,
  ...WEB_EXTENSIONS,
  ...TEXT_EXTENSIONS,
] as const;

export type FileExtension = (typeof ALL_EXTENSIONS)[number];

// Common MIME types (subset - backend has full mapping)
export const EXTENSION_TO_MIME: Record<string, string> = {
  // Documents
  pdf: "application/pdf",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  docm: "application/vnd.ms-word.document.macroEnabled.12",
  rtf: "application/rtf",
  epub: "application/epub+zip",
  pages: "application/vnd.apple.pages",
  // Presentations
  ppt: "application/vnd.ms-powerpoint",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  pptm: "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
  key: "application/vnd.apple.keynote",
  // Spreadsheets
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  xls: "application/vnd.ms-excel",
  xlsm: "application/vnd.ms-excel.sheet.macroEnabled.12",
  csv: "text/csv",
  numbers: "application/vnd.apple.numbers",
  ods: "application/vnd.oasis.opendocument.spreadsheet",
  tsv: "text/tab-separated-values",
  // Images
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  // Web
  html: "text/html",
  htm: "text/html",
  xml: "application/xml",
  // Text
  txt: "text/plain",
};

// Generate accept string for file inputs
// Includes both extensions (.pdf) and MIME types for maximum browser compatibility
export const FILE_ACCEPT_STRING = [
  ...ALL_EXTENSIONS.map((ext) => `.${ext}`),
  ...Object.values(EXTENSION_TO_MIME),
].join(",");

// User-friendly format list for error messages
export const ALLOWED_FORMATS_DISPLAY = ALL_EXTENSIONS.map((ext) => ext.toUpperCase()).join(", ");

// Check if extension is an image
export function isImageFile(extension: string): boolean {
  return IMAGE_EXTENSIONS.includes(extension.toLowerCase() as typeof IMAGE_EXTENSIONS[number]);
}

// Get file extension from filename
export function getFileExtension(filename: string): string | null {
  const parts = filename.toLowerCase().split(".");
  if (parts.length > 1) {
    return parts[parts.length - 1];
  }
  return null;
}

// Validate if file is supported
export function isAllowedFile(file: File): boolean {
  const type = (file.type || "").toLowerCase();
  const mime = Object.values(EXTENSION_TO_MIME).map((m) => m.toLowerCase());
  if (type && mime.includes(type)) return true;

  const name = file.name || "";
  const ext = getFileExtension(name);
  return ext !== null && ALL_EXTENSIONS.includes(ext as typeof ALL_EXTENSIONS[number]);
}

// File size limit (200MB default)
export const MAX_FILE_SIZE_MB = 200;
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
