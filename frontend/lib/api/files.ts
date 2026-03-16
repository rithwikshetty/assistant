import { fetchWithAuth } from "@/lib/api/auth";
import { parseApiError } from "@/lib/api/errors";
import type { ApiSchema } from "@/lib/api/generated/types";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

export type FileDownloadResponse = ApiSchema<"FileDownloadResponse">;

const DEFAULT_API_BASE_URL = getBackendBaseUrl();

export async function getFileDownloadUrl(options: {
  fileId: string;
  baseUrl?: string;
  signal?: AbortSignal;
}): Promise<FileDownloadResponse> {
  const { fileId, baseUrl = DEFAULT_API_BASE_URL, signal } = options;
  const response = await fetchWithAuth(`${baseUrl}/files/${fileId}/download`, {
    method: "GET",
    signal,
  });

  if (!response.ok) await parseApiError(response, "Failed to get download link");

  return response.json() as Promise<FileDownloadResponse>;
}
