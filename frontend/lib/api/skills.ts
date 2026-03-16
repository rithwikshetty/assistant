import { fetchWithAuth } from "@/lib/api/auth";
import { parseApiError } from "@/lib/api/errors";
import type { ApiSchema } from "@/lib/api/generated/types";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

export type SkillManifestFile = ApiSchema<"SkillManifestFile">;
export type SkillManifestItem = ApiSchema<"SkillManifestItem">;
export type SkillDetail = ApiSchema<"SkillDetailResponse">;
export type SkillStatus = SkillDetail["status"];
export type CustomSkillSummary = ApiSchema<"CustomSkillSummaryResponse">;
export type CustomSkillDetail = ApiSchema<"CustomSkillDetailResponse">;
export type SkillsManifest = ApiSchema<"SkillsManifestResponse">;
export type CustomSkillsListResponse = ApiSchema<"CustomSkillsListResponse">;

export interface SkillFileDownload {
  blob: Blob;
  filename: string;
  mime_type: string;
}

export type CreateCustomSkillRequest = ApiSchema<"CustomSkillCreateRequest">;
export type UpdateCustomSkillRequest = ApiSchema<"CustomSkillUpdateRequest">;
export type CustomSkillActionRequest = ApiSchema<"CustomSkillActionRequest">;
export type CustomSkillReferenceUpsertRequest = ApiSchema<"CustomSkillReferenceUpsertRequest">;

const API_BASE_URL = getBackendBaseUrl();

function parseDownloadFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) return null;

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      // Ignore invalid encoding and continue with plain filename parsing.
    }
  }

  const plainMatch = contentDisposition.match(/filename="?([^\";]+)"?/i);
  return plainMatch?.[1]?.trim() || null;
}

export async function getSkillsManifest(): Promise<SkillsManifest> {
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/manifest`, { method: "GET" });

  if (!response.ok) await parseApiError(response, "Failed to load skills manifest");
  return response.json() as Promise<SkillsManifest>;
}

export async function getSkillDetail(skillId: string): Promise<SkillDetail> {
  const normalizedSkillId = String(skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/${encodedSkillId}`, {
    method: "GET",
  });

  if (!response.ok) await parseApiError(response, "Failed to load skill content");
  return response.json() as Promise<SkillDetail>;
}

export async function getCustomSkills(): Promise<CustomSkillsListResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) await parseApiError(response, "Failed to load custom skills");
  return response.json() as Promise<CustomSkillsListResponse>;
}

export async function createCustomSkill(payload: CreateCustomSkillRequest = {}): Promise<CustomSkillDetail> {
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) await parseApiError(response, "Failed to create custom skill");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function getCustomSkillDetail(skillId: string): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}`, {
    method: "GET",
    cache: "no-store",
  });

  if (!response.ok) await parseApiError(response, "Failed to load custom skill");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function updateCustomSkill(skillId: string, payload: UpdateCustomSkillRequest): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) await parseApiError(response, "Failed to update custom skill");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function saveCustomSkillReference(options: {
  skillId: string;
  referencePath: string;
  content: string;
  expectedUpdatedAt?: string;
}): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(options.skillId || "").trim();
  const normalizedPath = String(options.referencePath || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");
  if (!normalizedPath) throw new Error("Reference path is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const encodedPath = normalizedPath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}/references/${encodedPath}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: options.content,
      expected_updated_at: options.expectedUpdatedAt,
    } satisfies CustomSkillReferenceUpsertRequest),
  });

  if (!response.ok) await parseApiError(response, "Failed to save reference");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function uploadCustomSkillFile(options: {
  skillId: string;
  category: "references" | "assets" | "templates";
  file: File;
  relativePath?: string;
}): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(options.skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const formData = new FormData();
  formData.append("file", options.file);
  formData.append("category", options.category);
  if (options.relativePath && options.relativePath.trim()) {
    formData.append("relative_path", options.relativePath.trim());
  }

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}/files`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) await parseApiError(response, "Failed to upload skill file");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function deleteCustomSkillFile(options: {
  skillId: string;
  filePath: string;
}): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(options.skillId || "").trim();
  const normalizedPath = String(options.filePath || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");
  if (!normalizedPath) throw new Error("File path is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const encodedPath = normalizedPath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}/files/${encodedPath}`, {
    method: "DELETE",
  });

  if (!response.ok) await parseApiError(response, "Failed to delete skill file");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function enableCustomSkill(skillId: string, expectedUpdatedAt?: string): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}/enable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_updated_at: expectedUpdatedAt } satisfies CustomSkillActionRequest),
  });

  if (!response.ok) await parseApiError(response, "Failed to enable custom skill");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function disableCustomSkill(skillId: string, expectedUpdatedAt?: string): Promise<CustomSkillDetail> {
  const normalizedSkillId = String(skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_updated_at: expectedUpdatedAt } satisfies CustomSkillActionRequest),
  });

  if (!response.ok) await parseApiError(response, "Failed to disable custom skill");
  return response.json() as Promise<CustomSkillDetail>;
}

export async function deleteCustomSkill(skillId: string): Promise<void> {
  const normalizedSkillId = String(skillId || "").trim();
  if (!normalizedSkillId) throw new Error("Skill id is required");

  const encodedSkillId = encodeURIComponent(normalizedSkillId);
  const response = await fetchWithAuth(`${API_BASE_URL}/skills/custom/${encodedSkillId}`, {
    method: "DELETE",
  });

  if (!response.ok) await parseApiError(response, "Failed to delete custom skill");
}

export async function downloadSkillFile(options: {
  downloadPath: string;
  fallbackFilename?: string;
  baseUrl?: string;
  signal?: AbortSignal;
}): Promise<SkillFileDownload> {
  const { downloadPath, fallbackFilename, baseUrl = API_BASE_URL, signal } = options;
  const normalizedPath = downloadPath.startsWith("/") ? downloadPath : `/${downloadPath}`;

  const response = await fetchWithAuth(`${baseUrl}${normalizedPath}`, {
    method: "GET",
    signal,
  });

  if (!response.ok) await parseApiError(response, "Failed to download skill file");

  const filename =
    parseDownloadFilename(response.headers.get("content-disposition")) ||
    fallbackFilename ||
    normalizedPath.split("/").at(-1) ||
    "skill-file";

  const mimeType = response.headers.get("content-type") || "application/octet-stream";
  const blob = await response.blob();

  return {
    blob,
    filename,
    mime_type: mimeType,
  };
}
