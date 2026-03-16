import { fetchWithAuth } from "@/lib/api/auth";
import type { ApiSchema } from "@/lib/api/generated/types";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

const API_BASE_URL = getBackendBaseUrl();

export type ChatProviderResponse = ApiSchema<"ChatProviderResponse">;
export type ChatProviderUpdate = ApiSchema<"ChatProviderUpdate">;
export type Provider = ChatProviderResponse["provider"];

export async function fetchChatProvider(): Promise<ChatProviderResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/chat/provider`, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Failed to load model configuration");
  }
  return res.json();
}

export async function updateChatProvider(update: ChatProviderUpdate): Promise<ChatProviderResponse> {
  const res = await fetchWithAuth(`${API_BASE_URL}/admin/chat/provider`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Failed to update model configuration");
  }
  return res.json();
}
