/**
 * API client for chat routes.
 *
 * Live chat transport uses the app-wide WebSocket while
 * timeline/runtime fetches remain plain HTTP.
 */

import { fetchWithAuth } from "./auth";
import { parseApiError } from "./errors";
import {
  parseConversationRuntimeResponse,
  parseCreateRunResponse,
  parseRunStatusResponse,
  parseTimelinePageResponse,
} from "@/lib/contracts/chat";
import type { RequestUserInputSubmissionPayload } from "@/lib/contracts/chat-interactive";
import type {
  ConversationRuntimeResponse,
  CreateRunResponse,
  RunStatusResponse,
  StreamEvent,
  TimelinePageResponse,
} from "@/lib/contracts/chat";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";
import { getChatWsTransport } from "@/lib/chat/wsTransport";

const API_URL = getBackendBaseUrl();

export type {
  CreateConversationResponse,
  CreateRunResponse,
  RunStatusResponse,
  ConversationRuntimeResponse,
  RunActivityPayload,
  RunActivityItemResponse,
  StreamEvent,
  StreamTransportEvent,
  TimelineItem,
  TimelineMessagePayload,
  TimelinePageResponse,
  StreamStatePendingRequestResponse,
} from "@/lib/contracts/chat";
export type {
  InteractivePendingRequestResponse,
  InteractivePendingRequestTransport,
  RequestUserInputPendingRequestResponse,
  RequestUserInputPendingRequestTransport,
  RequestUserInputSubmissionPayload,
} from "@/lib/contracts/chat-interactive";

export async function createRun(options: {
  conversationId: string;
  text: string;
  attachmentIds?: string[];
  requestId?: string | null;
  abortSignal?: AbortSignal;
}): Promise<CreateRunResponse> {
  const response = await fetchWithAuth(
    `${API_URL}/conversations/${options.conversationId}/runs`,
    {
      method: "POST",
      signal: options.abortSignal,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text: options.text,
        attachment_ids: options.attachmentIds,
        request_id: options.requestId,
      }),
    }
  );

  if (!response.ok) await parseApiError(response, "Failed to create run");

  return parseCreateRunResponse(await response.json());
}

export async function fetchTimelinePage(options: {
  conversationId: string;
  limit: number;
  cursor?: string | null;
}): Promise<TimelinePageResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options.limit));
  if (options.cursor) {
    params.set("cursor", options.cursor);
  }
  const response = await fetchWithAuth(
    `${API_URL}/conversations/${options.conversationId}/timeline?${params.toString()}`,
    { method: "GET" },
  );

  if (!response.ok) await parseApiError(response, "Failed to fetch timeline");

  return parseTimelinePageResponse(await response.json());
}

const RUNTIME_FETCH_TIMEOUT_MS = 8_000;

export async function fetchConversationRuntime(
  conversationId: string,
): Promise<ConversationRuntimeResponse> {
  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), RUNTIME_FETCH_TIMEOUT_MS);
  try {
    const response = await fetchWithAuth(
      `${API_URL}/conversations/${conversationId}/runtime`,
      { method: "GET", signal: timeoutController.signal },
    );

    if (!response.ok) await parseApiError(response, "Failed to fetch conversation runtime");

    return parseConversationRuntimeResponse(await response.json());
  } finally {
    clearTimeout(timer);
  }
}

export async function cancelRun(
  runId: string,
): Promise<RunStatusResponse> {
  const response = await fetchWithAuth(
    `${API_URL}/conversations/runs/${runId}/cancel`,
    { method: "POST" },
  );

  if (!response.ok) await parseApiError(response, "Failed to cancel run");

  return parseRunStatusResponse(await response.json());
}

export async function submitRunUserInput(options: {
  runId: string;
  result: RequestUserInputSubmissionPayload;
  toolCallId?: string;
}): Promise<RunStatusResponse> {
  const response = await fetchWithAuth(
    `${API_URL}/conversations/runs/${options.runId}/user-input`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: options.toolCallId,
        result: options.result,
      }),
    },
  );

  if (!response.ok) await parseApiError(response, "Failed to submit run input");

  return parseRunStatusResponse(await response.json());
}

/**
 * Stream chat events through the shared chat WebSocket transport.
 *
 * Reconnection and replay are handled by the transport itself using the
 * latest delivered conversation event id as the resume cursor.
 */
export async function* streamChat(
  conversationId: string,
  options?: {
    sinceStreamEventId?: number;
    runMessageId?: string | null;
    abortSignal?: AbortSignal;
    onTransportProgress?: (progress: { eventId: number | null }) => void;
  }
): AsyncGenerator<StreamEvent, void, unknown> {
  const {
    sinceStreamEventId = 0,
    runMessageId = null,
    abortSignal,
    onTransportProgress,
  } = options || {};
  const transport = getChatWsTransport();
  const queue: StreamEvent[] = [];
  let resolvePending: (() => void) | null = null;

  const wake = () => {
    const pending = resolvePending;
    resolvePending = null;
    pending?.();
  };

  const unsubscribe = transport.subscribeConversation(
    {
      conversationId,
      sinceStreamEventId,
      runMessageId,
    },
    (event) => {
      onTransportProgress?.({ eventId: event.id });
      queue.push(event);
      wake();
    },
  );

  const abortHandler = () => {
    wake();
  };
  abortSignal?.addEventListener("abort", abortHandler);

  try {
    while (!abortSignal?.aborted) {
      if (queue.length === 0) {
        await new Promise<void>((resolve) => {
          resolvePending = resolve;
        });
        continue;
      }

      const event = queue.shift();
      if (!event) {
        continue;
      }
      yield event;
      if (
        event.type === "done" ||
        event.type === "error" ||
        event.type === "run.failed" ||
        event.type === "no_active_stream"
      ) {
        return;
      }
    }
  } finally {
    abortSignal?.removeEventListener("abort", abortHandler);
    unsubscribe();
  }
}
