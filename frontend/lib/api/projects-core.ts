import { fetchWithAuth } from "@/lib/api/auth";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";
import { parseApiError } from "@/lib/api/errors";
import type { ApiSchema } from "@/lib/api/generated/types";
import { parseSse } from "@/lib/utils/sse-parser";

export type Project = ApiSchema<"ProjectResponse">;
export type ProjectWithConversationCount = ApiSchema<"ProjectWithConversationCount">;
export type CreateProjectRequest = ApiSchema<"ProjectCreate">;
export type UpdateProjectRequest = ApiSchema<"ProjectUpdate">;
export type ProjectKnowledgeUploader = ApiSchema<"ProjectKnowledgeUploader">;
export type ProjectKnowledgeFileItem = ApiSchema<"ProjectKnowledgeFile">;
export type ProjectKnowledgeFilesPageResponse = ApiSchema<"ProjectKnowledgeFilesPageResponse">;
export type ProjectKnowledgeSummaryResponse = ApiSchema<"ProjectKnowledgeSummaryResponse">;
export type ProjectKnowledgeSummaryItem = ApiSchema<"ProjectKnowledgeSummaryItem">;
export type ProjectKnowledgeContextResponse = ApiSchema<"ProjectKnowledgeContextResponse">;
export type ProjectKnowledgeProcessingStatus = ApiSchema<"ProjectKnowledgeProcessingStatus">;

export type ProjectKnowledgeProcessingStatusStreamEvent = {
  type: "processing_status" | "done" | "error";
  data?: unknown;
};

export type ProjectKnowledgeArchiveJobResponse = ApiSchema<"ProjectKnowledgeArchiveJobResponse">;

const API_BASE_URL = getBackendBaseUrl();

export async function createProject(data: CreateProjectRequest): Promise<Project> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) await parseApiError(response, "Failed to create project");

  return response.json();
}

export async function listProjects(): Promise<ProjectWithConversationCount[]> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects`, {
    method: "GET",
  });

  if (!response.ok) await parseApiError(response, "Failed to list projects");

  return response.json();
}

export async function getProject(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}`, {
    method: "GET",
  });

  if (!response.ok) await parseApiError(response, "Failed to get project");

  return response.json();
}

export async function updateProject(
  projectId: string,
  data: UpdateProjectRequest
): Promise<Project> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) await parseApiError(response, "Failed to update project");

  return response.json();
}

export async function uploadProjectPublicImage(projectId: string, file: File): Promise<Project> {
  const formData = new FormData();
  formData.append("image", file);
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/public-image`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) await parseApiError(response, "Failed to upload project image");
  return response.json();
}

export async function deleteProjectPublicImage(projectId: string): Promise<Project> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/public-image`, {
    method: "DELETE",
  });
  if (!response.ok) await parseApiError(response, "Failed to remove project image");
  return response.json();
}

export async function uploadProjectKnowledgeFile(
  projectId: string,
  file: File,
  options?: { redact?: boolean; signal?: AbortSignal }
): Promise<ProjectKnowledgeFileItem> {
  const formData = new FormData();
  formData.append("file", file);

  const query = options?.redact ? "?redact=true" : "";
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/upload${query}`, {
    method: "POST",
    body: formData,
    signal: options?.signal,
  });

  if (!response.ok) await parseApiError(response, "Failed to upload knowledge file");

  return response.json() as Promise<ProjectKnowledgeFileItem>;
}

export async function getProjectKnowledgeSummary(projectId: string): Promise<ProjectKnowledgeSummaryResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/summary`, {
    method: "GET",
  });

  if (!response.ok) await parseApiError(response, "Failed to load project knowledge summary");

  return response.json() as Promise<ProjectKnowledgeSummaryResponse>;
}

export async function listProjectKnowledgeFiles(
  projectId: string,
  options?: { limit?: number; offset?: number },
): Promise<ProjectKnowledgeFilesPageResponse> {
  const limit = Math.max(1, Math.min(options?.limit ?? 50, 200));
  const offset = Math.max(0, options?.offset ?? 0);
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/files?${query.toString()}`, {
    method: "GET",
  });

  if (!response.ok) await parseApiError(response, "Failed to load project knowledge files");

  return response.json() as Promise<ProjectKnowledgeFilesPageResponse>;
}

export async function deleteProjectKnowledgeFile(projectId: string, fileId: string): Promise<void> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/files/${fileId}`, {
    method: "DELETE",
  });

  if (!response.ok && response.status !== 404) await parseApiError(response, "Failed to delete knowledge file");
}

export async function deleteAllProjectKnowledgeFiles(projectId: string): Promise<{ deleted: number }> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/files`, {
    method: "DELETE",
  });

  if (!response.ok) await parseApiError(response, "Failed to delete knowledge files");
  return response.json() as Promise<{ deleted: number }>;
}

export async function createProjectKnowledgeArchiveJob(
  projectId: string,
  options?: { signal?: AbortSignal },
): Promise<ProjectKnowledgeArchiveJobResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/archive-jobs`, {
    method: "POST",
    signal: options?.signal,
  });

  if (!response.ok) await parseApiError(response, "Failed to start project archive");

  return response.json() as Promise<ProjectKnowledgeArchiveJobResponse>;
}

export async function getProjectKnowledgeArchiveJob(
  projectId: string,
  jobId: string,
  options?: { signal?: AbortSignal },
): Promise<ProjectKnowledgeArchiveJobResponse> {
  const response = await fetchWithAuth(`${API_BASE_URL}/projects/${projectId}/knowledge-base/archive-jobs/${jobId}`, {
    method: "GET",
    signal: options?.signal,
  });

  if (!response.ok) await parseApiError(response, "Failed to load project archive status");

  return response.json() as Promise<ProjectKnowledgeArchiveJobResponse>;
}

export async function* streamProjectKnowledgeProcessingStatus(
  projectId: string,
  options?: {
    abortSignal?: AbortSignal;
    maxRetries?: number;
    retryDelayMs?: number;
  },
): AsyncGenerator<ProjectKnowledgeProcessingStatusStreamEvent, void, unknown> {
  const {
    abortSignal,
    maxRetries = 5,
    retryDelayMs = 500,
  } = options || {};
  let retries = 0;

  while (retries < maxRetries) {
    if (abortSignal?.aborted) return;

    try {
      const response = await fetchWithAuth(
        `${API_BASE_URL}/projects/${projectId}/knowledge-base/processing-status/stream`,
        {
          method: "GET",
          headers: { Accept: "text/event-stream" },
          cache: "no-store",
          signal: abortSignal,
        },
      );

      if (response.status === 401) {
        yield { type: "error", data: { message: "Authentication failed" } };
        return;
      }

      if (!response.ok || !response.body) {
        throw new Error(`Processing status stream failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const parserAbortController = abortSignal ? null : new AbortController();
      const parserAbortSignal = abortSignal ?? parserAbortController!.signal;
      let sawTerminalEvent = false;

      for await (const event of parseSse<ProjectKnowledgeProcessingStatusStreamEvent>(reader, parserAbortSignal)) {
        if (!event || typeof event.type !== "string") continue;

        retries = 0;
        yield event;
        if (event.type === "done" || event.type === "error") {
          sawTerminalEvent = true;
          return;
        }
      }

      if (!sawTerminalEvent) {
        retries += 1;
        if (retries >= maxRetries) {
          yield { type: "error", data: { message: "Connection failed" } };
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs * retries));
      }
    } catch {
      if (abortSignal?.aborted) return;

      retries += 1;
      if (retries >= maxRetries) {
        yield { type: "error", data: { message: "Connection failed" } };
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, retryDelayMs * retries));
    }
  }
}

// No compatibility exports; codebase uses Project naming going forward.
