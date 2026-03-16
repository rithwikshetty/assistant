import { fetchWithAuth } from "@/lib/api/auth";
import { parseApiError } from "@/lib/api/errors";
import type { ApiSchema } from "@/lib/api/generated/types";

export type StagedFileUploadResponse = ApiSchema<"StagedFileResponse">;

export async function uploadStagedFile(options: {
  baseUrl: string;
  file: File;
  uploadId?: string | null;
  redact?: boolean;
  signal?: AbortSignal;
}): Promise<StagedFileUploadResponse> {
  const { baseUrl, file, uploadId, signal, redact = false } = options;
  const formData = new FormData();
  formData.append("file", file);
  if (uploadId) formData.append("draft_id", uploadId);

  const url = `${baseUrl}/staged-files/upload${redact ? "?redact=true" : ""}`;

  const res = await fetchWithAuth(url, {
    method: "POST",
    body: formData,
    signal,
  });
  if (!res.ok) await parseApiError(res, "Staged upload failed");
  return res.json() as Promise<StagedFileUploadResponse>;
}

export async function getStagedFile(options: {
  baseUrl: string;
  stagedId: string;
  signal?: AbortSignal;
}): Promise<StagedFileUploadResponse> {
  const { baseUrl, stagedId, signal } = options;
  const res = await fetchWithAuth(`${baseUrl}/staged-files/${stagedId}`, {
    method: "GET",
    signal,
  });
  if (!res.ok) await parseApiError(res, "Failed to load staged file");
  return res.json() as Promise<StagedFileUploadResponse>;
}

export async function cancelStagedUpload(options: {
  baseUrl: string;
  uploadId: string;
  signal?: AbortSignal;
}): Promise<void> {
  const { baseUrl, uploadId, signal } = options;
  const res = await fetchWithAuth(`${baseUrl}/staged-files/uploads/${encodeURIComponent(uploadId)}/cancel`, {
    method: "POST",
    signal,
  });
  if (!res.ok && res.status !== 404) {
    await parseApiError(res, "Failed to cancel staged upload");
  }
}

export async function deleteStagedFile(options: {
  baseUrl: string;
  stagedId: string;
  signal?: AbortSignal;
}): Promise<void> {
  const { baseUrl, stagedId, signal } = options;
  const res = await fetchWithAuth(`${baseUrl}/staged-files/${stagedId}`, {
    method: "DELETE",
    signal,
  });
  if (!res.ok && res.status !== 404) {
    await parseApiError(res, "Failed to delete staged file");
  }
}
