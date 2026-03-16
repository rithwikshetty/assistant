import { fetchWithAuth } from "@/lib/api/auth";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

// All frontend API calls stay on the current browser origin during local dev;
// Vite proxies them to whichever backend port was reserved.
const API_BASE_URL = getBackendBaseUrl();

export interface SuggestionsResponse {
  messageId: string;
  suggestions: string[];
}

export class SuggestionsApiError extends Error {
  status?: number;
  detail?: string;
}

export async function generateMessageSuggestions(
  conversationId: string,
  messageId: string
): Promise<SuggestionsResponse> {
  const url = `${API_BASE_URL}/conversations/${conversationId}/messages/${messageId}/suggestions`;

  const response = await fetchWithAuth(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    const err = new SuggestionsApiError(
      detail || `Failed to generate suggestions: ${response.statusText}`,
    );
    err.status = response.status;
    err.detail = detail;
    throw err;
  }

  const payload = await response.json();
  return {
    messageId:
      typeof payload?.message_id === "string" && payload.message_id.trim().length > 0
        ? payload.message_id.trim()
        : messageId,
    suggestions: Array.isArray(payload?.suggestions)
      ? payload.suggestions.filter((entry: unknown): entry is string => typeof entry === "string")
      : [],
  };
}
