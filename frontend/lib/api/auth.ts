// Local workspace API helpers.
import {
  getBackendToken,
  clearBackendToken,
} from '@/lib/utils/cookie-manager';
import {
  conversationResponseToSummary,
  parseConversationResponsePayload,
  parseConversationResponsePayloadList,
  parseTimelinePageResponse,
} from '@/lib/contracts/chat';
import type {
  ConversationResponsePayload,
  ConversationSummary,
} from '@/lib/contracts/chat';
import { getBackendBaseUrl } from '@/lib/utils/backend-url';

const API_BASE_URL = getBackendBaseUrl();

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  user_tier?: string;
  last_login_at?: string;
  last_login_country?: string;
}

export type {
  ConversationSummary,
  ConversationResponsePayload,
  ConversationContextUsage,
} from '@/lib/contracts/chat';
export { conversationResponseToSummary } from '@/lib/contracts/chat';

export interface BulkArchiveResponse {
  archived_ids: string[];
  already_archived_ids: string[];
  not_found_ids: string[];
  archived_timestamps: Record<string, string>;
}

export interface ApiError {
  message: string;
  status?: number;
  code?: string;
  detail?: string;
  retryAfterSeconds?: number;
}

async function buildApiError(response: Response, fallbackMessage: string): Promise<ApiError> {
  const retryAfterHeader = response.headers.get("retry-after");
  const retryAfterSeconds = retryAfterHeader && Number.isFinite(Number(retryAfterHeader))
    ? Math.max(0, Number(retryAfterHeader))
    : undefined;

  let detail: string | undefined;
  let code: string | undefined;

  try {
    const payload = await response.json() as { detail?: unknown; code?: unknown; message?: unknown };
    if (typeof payload?.detail === "string" && payload.detail.trim().length > 0) {
      detail = payload.detail.trim();
    } else if (typeof payload?.message === "string" && payload.message.trim().length > 0) {
      detail = payload.message.trim();
    }
    if (typeof payload?.code === "string" && payload.code.trim().length > 0) {
      code = payload.code.trim();
    }
  } catch {}

  return {
    message: detail || fallbackMessage,
    status: response.status,
    code,
    detail,
    retryAfterSeconds,
  };
}

// Get current user from backend
export async function getCurrentUser(): Promise<User | null> {
  try {
    const response = await fetchWithAuth(`${API_BASE_URL}/auth/me`);

    if (!response.ok) {
      throw new Error(`Failed to get current user: ${response.statusText}`);
    }

    return response.json();
  } catch {
    return null;
  }
}

// Get user's conversations from backend
export async function getUserConversations(): Promise<ConversationSummary[]> {
  const token = getBackendToken();

  if (!token) {
    return [];
  }

  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/`, {
    cache: 'no-store',
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      return [];
    }
    throw await buildApiError(response, `Failed to get conversations (${response.status})`);
  }

  const payload = parseConversationResponsePayloadList(await response.json());
  return payload.map(conversationResponseToSummary);
}

// Toggle pin/unpin for a conversation
export async function togglePinConversation(conversationId: string): Promise<ConversationSummary> {
  const token = getBackendToken();

  if (!token) {
    throw new Error('No authentication token available');
  }

  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/${conversationId}/pin`, {
    method: 'PATCH',
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      throw new Error('Authentication failed');
    }
    if (response.status === 404) {
      throw new Error('Conversation not found');
    }
    const text = await response.text();
    throw new Error(text || 'Failed to update pin status');
  }

  const payload = parseConversationResponsePayload(await response.json());
  return conversationResponseToSummary(payload);
}

// Delete multiple conversations
export async function deleteConversations(conversationIds: string[]): Promise<BulkArchiveResponse> {
  const token = getBackendToken();

  if (!token) {
    throw new Error('No authentication token available');
  }

  const uniqueIds = Array.from(new Set(conversationIds.filter((id): id is string => typeof id === 'string' && id.trim().length > 0)));

  if (uniqueIds.length === 0) {
    throw new Error('No conversations selected for deletion');
  }

  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/bulk-archive`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ conversation_ids: uniqueIds }),
  });

  if (response.status === 401) {
    clearBackendToken();
    throw new Error('Authentication failed');
  }

  if (!response.ok) {
    let message = `Failed to delete conversations: ${response.statusText}`;
    try {
      const errorBody = await response.json();
      const detail = typeof (errorBody as { detail?: unknown })?.detail === 'string'
        ? (errorBody as { detail: string }).detail.trim()
        : undefined;
      if (detail) {
        message = detail;
      }
    } catch {}
    throw new Error(message);
  }

  let payload: Partial<BulkArchiveResponse> = {};
  try {
    payload = await response.json() as Partial<BulkArchiveResponse>;
  } catch {
    payload = {};
  }

  const normalizeArray = (value: unknown): string[] => Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [];
  const normalizedTimestamps: Record<string, string> = {};
  if (payload?.archived_timestamps && typeof payload.archived_timestamps === 'object') {
    for (const [key, value] of Object.entries(payload.archived_timestamps as Record<string, unknown>)) {
      if (typeof value === 'string') {
        normalizedTimestamps[key] = value;
      }
    }
  }

  return {
    archived_ids: normalizeArray(payload.archived_ids),
    already_archived_ids: normalizeArray(payload.already_archived_ids),
    not_found_ids: normalizeArray(payload.not_found_ids),
    archived_timestamps: normalizedTimestamps,
  };
}

export async function getLatestConversationMessageId(
  conversationId: string,
): Promise<string | null> {
  const response = await fetchWithAuth(
    `${API_BASE_URL}/conversations/${conversationId}/timeline?limit=1`,
  );

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      throw new Error("Authentication failed");
    }
    throw new Error(`Failed to fetch timeline: ${response.status}`);
  }

  const payload = parseTimelinePageResponse(await response.json().catch(() => ({})));
  const items = payload.items;
  const last = items.length > 0 ? items[items.length - 1] : null;
  return typeof last?.id === "string" && last.id ? last.id : null;
}

export async function createConversation(options?: {
  conversationId?: string;
  requestId?: string | null;
  projectId?: string | null;
  title?: string | null;
}): Promise<ConversationResponsePayload> {
  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      conversation_id: options?.conversationId ?? undefined,
      request_id: options?.requestId ?? undefined,
      project_id: options?.projectId ?? undefined,
      title: options?.title ?? undefined,
    }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      throw new Error('Authentication failed');
    }
    const error = await response.json().catch(() => ({}));
    const detail = typeof error?.detail === 'string' && error.detail.trim().length > 0
      ? error.detail
      : `Failed to create conversation: ${response.status}`;
    throw new Error(detail);
  }

  return parseConversationResponsePayload(await response.json());
}

export async function branchConversation(
  conversationId: string,
  messageId: string,
): Promise<ConversationResponsePayload> {
  const token = getBackendToken();

  if (!token) {
    throw new Error('No authentication token available');
  }

  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/${conversationId}/branch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message_id: messageId }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      throw new Error('Authentication failed');
    }
    if (response.status === 404) {
      throw new Error('Conversation or message not found');
    }
    throw new Error(`Failed to branch conversation: ${response.statusText}`);
  }

  return parseConversationResponsePayload(await response.json());
}

export async function updateConversationProject(
  conversationId: string,
  projectId: string | null,
): Promise<ConversationResponsePayload> {
  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/${conversationId}/project`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ project_id: projectId }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      throw new Error('Authentication failed');
    }
    if (response.status === 404) {
      const body = await response.json().catch(() => null);
      const detail = typeof body?.detail === 'string' ? body.detail : null;
      if (detail === 'Project not found') {
        throw new Error('Project not found');
      }
      throw new Error('Conversation not found');
    }
    const text = await response.text();
    throw new Error(text || 'Failed to update conversation project');
  }

  return parseConversationResponsePayload(await response.json());
}

// Rename a conversation
export async function renameConversation(conversationId: string, newTitle: string): Promise<void> {
  const token = getBackendToken();

  if (!token) {
    throw new Error('No authentication token available');
  }

  const response = await fetchWithAuth(`${API_BASE_URL}/conversations/${conversationId}/title`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      title: newTitle
    }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearBackendToken();
      throw new Error('Authentication failed');
    }
    if (response.status === 404) {
      throw new Error('Conversation not found');
    }
    throw new Error(`Failed to rename conversation: ${response.statusText}`);
  }
}

function getClientTimeContextHeaders(): Record<string, string> {
  if (typeof window === "undefined") {
    return {};
  }

  const headers: Record<string, string> = {};

  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (typeof timezone === "string" && timezone.trim()) {
      headers["X-User-Timezone"] = timezone.trim();
    }
  } catch {}

  try {
    const locale = window.navigator?.language;
    if (typeof locale === "string" && locale.trim()) {
      headers["X-User-Locale"] = locale.trim();
    }
  } catch {}

  return headers;
}

// Fetch helper for the local single-user workspace runtime.
export async function fetchWithAuth(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getBackendToken();
  const clientTimeContextHeaders = getClientTimeContextHeaders();

  const requestOptions = {
    ...options,
    headers: {
      ...clientTimeContextHeaders,
      ...options.headers,
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
  };

  const response = await fetch(url, requestOptions);
  return response;
}

// Re-export for use in other API modules
export { getBackendToken };
