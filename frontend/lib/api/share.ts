import { getBackendBaseUrl } from "../utils/backend-url";
import { fetchWithAuth } from "./auth";
import type { ApiSchema } from "./generated/types";

export type ShareResponse = ApiSchema<"ShareResponse">;
export type ShareImportResponse = ApiSchema<"ShareImportResponse">;

export async function createShareLink(conversationId: string): Promise<ShareResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseUrl()}/conversations/${conversationId}/share`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create share link" }));
    throw new Error(error.detail || "Failed to create share link");
  }

  return response.json();
}

export async function importSharedConversation(shareToken: string): Promise<ShareImportResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseUrl()}/share/${shareToken}/import`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to import conversation" }));
    throw new Error(error.detail || "Failed to import conversation");
  }

  return response.json();
}
