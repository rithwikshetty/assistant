import { getBackendBaseUrl } from "@/lib/utils/backend-url";
import { parseStreamEvent } from "@/lib/contracts/chat";
import type { StreamTransportEvent } from "@/lib/contracts/chat";
import { parseChatUserEvent, type ChatUserEvent } from "@/lib/chat/ws-user-events";
import {
  CHAT_WS_CHANNELS,
  CHAT_WS_METHODS,
  type ChatWsPushEnvelope,
  type ChatWsRequestBody,
  type ChatWsResponseEnvelope,
} from "@/lib/chat/generated/ws-contract";
import { isRecord } from "@/lib/contracts/contract-utils";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";

type WsRequestEnvelope = {
  id: string;
  body: ChatWsRequestBody;
};

type UserEventListener = (event: ChatUserEvent) => void;
type ConversationEventListener = (event: StreamTransportEvent) => void;

type PendingRequest = {
  envelope: WsRequestEnvelope;
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
  sent: boolean;
};

type ConversationSubscription = {
  conversationId: string;
  runMessageId: string | null;
  lastEventId: number;
  listeners: Set<ConversationEventListener>;
};

const REQUEST_TIMEOUT_MS = 10_000;
const MAX_RECONNECT_DELAY_MS = 5_000;
const WS_CONNECTION_CLOSED_ERROR = "WebSocket connection closed";

function normalizeNonNegativeInt(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(0, Math.floor(value));
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return Math.max(0, Math.floor(parsed));
    }
  }
  return fallback;
}

function extractEventRunMessageId(raw: unknown): string | null {
  if (!isRecord(raw)) return null;
  const data = isRecord(raw.data) ? raw.data : null;
  return normalizeNonEmptyString(data?.runMessageId);
}

function decodeMessage(raw: unknown): ChatWsResponseEnvelope | ChatWsPushEnvelope | null {
  const text =
    typeof raw === "string"
      ? raw
      : raw instanceof ArrayBuffer
        ? new TextDecoder().decode(raw)
        : null;
  if (text === null) return null;

  try {
    const parsed = JSON.parse(text);
    if (!isRecord(parsed)) return null;
    if (
      parsed.type === "push" &&
      (parsed.channel === CHAT_WS_CHANNELS.userEvent || parsed.channel === CHAT_WS_CHANNELS.streamEvent)
    ) {
      return parsed as ChatWsPushEnvelope;
    }
    if (typeof parsed.id === "string") {
      return parsed as ChatWsResponseEnvelope;
    }
    return null;
  } catch {
    return null;
  }
}

function buildWebSocketUrl(): string | null {
  const baseUrl = getBackendBaseUrl();
  const url = new URL(baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/conversations/ws`;
  return url.toString();
}

export class ChatWsTransport {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pending = new Map<string, PendingRequest>();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;
  private readonly userEventListeners = new Set<UserEventListener>();
  private readonly conversationSubscriptions = new Map<string, ConversationSubscription>();

  subscribeUserEvents(listener: UserEventListener): () => void {
    this.userEventListeners.add(listener);
    this.ensureConnection();
    return () => {
      this.userEventListeners.delete(listener);
    };
  }

  subscribeConversation(
    options: {
      conversationId: string;
      sinceStreamEventId?: number;
      runMessageId?: string | null;
    },
    listener: ConversationEventListener,
  ): () => void {
    const conversationId = options.conversationId.trim();
    if (!conversationId) {
      throw new Error("conversationId is required");
    }

    let subscription = this.conversationSubscriptions.get(conversationId);
    const requestedRunMessageId = normalizeNonEmptyString(options.runMessageId) ?? null;
    const requestedSinceEventId = normalizeNonNegativeInt(options.sinceStreamEventId, 0);
    if (!subscription) {
      subscription = {
        conversationId,
        runMessageId: requestedRunMessageId,
        lastEventId: requestedSinceEventId,
        listeners: new Set(),
      };
      this.conversationSubscriptions.set(conversationId, subscription);
    } else {
      const runChanged = subscription.runMessageId !== requestedRunMessageId;
      const cursorRewound = requestedSinceEventId < subscription.lastEventId;
      subscription.runMessageId = requestedRunMessageId;
      subscription.lastEventId = runChanged || cursorRewound
        ? requestedSinceEventId
        : Math.max(subscription.lastEventId, requestedSinceEventId);
    }

    subscription.listeners.add(listener);
    this.ensureConnection();
    if (this.ws?.readyState === WebSocket.OPEN) {
      void this.subscribeRemote(subscription);
    }

    return () => {
      const current = this.conversationSubscriptions.get(conversationId);
      if (!current) return;
      current.listeners.delete(listener);
      if (current.listeners.size > 0) return;
      this.conversationSubscriptions.delete(conversationId);
      if (this.ws?.readyState === WebSocket.OPEN) {
        void this.request(CHAT_WS_METHODS.unsubscribeStream, { conversationId }).catch(() => undefined);
      }
    };
  }

  async request<T = unknown>(method: ChatWsRequestBody["_tag"], params?: Record<string, unknown>): Promise<T> {
    const id = String(this.nextId++);
    const envelope: WsRequestEnvelope = {
      id,
      body: (params ? { ...params, _tag: method } : { _tag: method }) as ChatWsRequestBody,
    };

    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`WebSocket request timed out: ${method}`));
      }, REQUEST_TIMEOUT_MS);

      this.pending.set(id, {
        envelope,
        resolve: resolve as (value: unknown) => void,
        reject,
        timeout,
        sent: false,
      });

      this.ensureConnection();
      this.flushPendingRequests();
    });
  }

  dispose(): void {
    this.disposed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.rejectPendingRequests("WebSocket transport disposed");
    this.ws?.close();
    this.ws = null;
  }

  private rejectPendingRequests(message: string): void {
    for (const [id, pending] of this.pending.entries()) {
      clearTimeout(pending.timeout);
      pending.reject(new Error(message));
      this.pending.delete(id);
    }
  }

  private emitConversationError(subscription: ConversationSubscription, message: string, code = "WS_SUBSCRIBE"): void {
    const syntheticEvent = parseStreamEvent({
      id: subscription.lastEventId + 1,
      type: "error",
      data: {
        message,
        code,
      },
    });
    if (!syntheticEvent) return;
    subscription.lastEventId = syntheticEvent.id;
    for (const listener of subscription.listeners) {
      listener(syntheticEvent);
    }
  }

  private async subscribeRemote(subscription: ConversationSubscription): Promise<void> {
    try {
      await this.request(CHAT_WS_METHODS.subscribeStream, {
        conversationId: subscription.conversationId,
        sinceStreamEventId: subscription.lastEventId,
        ...(subscription.runMessageId ? { runMessageId: subscription.runMessageId } : {}),
      });
    } catch (error) {
      if (error instanceof Error && error.message === WS_CONNECTION_CLOSED_ERROR) {
        return;
      }
      const message =
        error instanceof Error && error.message.trim().length > 0
          ? error.message
          : "Failed to subscribe to conversation stream";
      this.emitConversationError(subscription, message);
    }
  }

  private ensureConnection(): void {
    if (this.disposed) return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const url = buildWebSocketUrl();
    if (!url) return;

    const ws = new WebSocket(url);
    this.ws = ws;

    ws.addEventListener("open", () => {
      this.reconnectAttempt = 0;
      this.flushPendingRequests();
      for (const subscription of this.conversationSubscriptions.values()) {
        void this.subscribeRemote(subscription);
      }
    });

    ws.addEventListener("message", (event) => {
      this.handleMessage(event.data);
    });

    ws.addEventListener("close", () => {
      if (this.ws === ws) {
        this.ws = null;
      }
      this.rejectPendingRequests(WS_CONNECTION_CLOSED_ERROR);
      if (!this.disposed) {
        this.scheduleReconnect();
      }
    });

    ws.addEventListener("error", () => {
      // Close will follow.
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.disposed) return;
    const delay = Math.min(500 * (this.reconnectAttempt + 1), MAX_RECONNECT_DELAY_MS);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.ensureConnection();
    }, delay);
  }

  private flushPendingRequests(): void {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      return;
    }
    for (const [id, pending] of this.pending.entries()) {
      if (pending.sent) {
        continue;
      }
      if (!this.pending.has(id)) {
        continue;
      }
      this.ws.send(JSON.stringify(pending.envelope));
      pending.sent = true;
    }
  }

  private handleMessage(raw: unknown): void {
    const message = decodeMessage(raw);
    if (!message) return;

    if ("type" in message) {
      this.handlePush(message);
      return;
    }

    const pending = this.pending.get(message.id);
    if (!pending) return;
    clearTimeout(pending.timeout);
    this.pending.delete(message.id);

    const errorMessage = normalizeNonEmptyString(message.error?.message);
    if (errorMessage) {
      pending.reject(new Error(errorMessage));
      return;
    }
    pending.resolve(message.result);
  }

  private handlePush(push: ChatWsPushEnvelope): void {
    if (push.channel === CHAT_WS_CHANNELS.userEvent) {
      const event = parseChatUserEvent(push.data);
      if (!event) return;
      for (const listener of this.userEventListeners) {
        listener(event);
      }
      return;
    }

    if (push.channel !== CHAT_WS_CHANNELS.streamEvent || !isRecord(push.data)) {
      return;
    }

    const conversationId = normalizeNonEmptyString(push.data.conversationId);
    if (!conversationId) return;
    const subscription = this.conversationSubscriptions.get(conversationId);
    if (!subscription) return;
    const eventRunMessageId = extractEventRunMessageId(push.data.event);
    if (
      subscription.runMessageId &&
      eventRunMessageId &&
      eventRunMessageId !== subscription.runMessageId
    ) {
      return;
    }

    const event = parseStreamEvent(push.data.event);
    if (!event) return;
    subscription.lastEventId = Math.max(subscription.lastEventId, event.id);
    for (const listener of subscription.listeners) {
      listener(event);
    }
  }
}

let singleton: ChatWsTransport | null = null;

export function getChatWsTransport(): ChatWsTransport {
  if (!singleton) {
    singleton = new ChatWsTransport();
  }
  return singleton;
}

export function disposeChatWsTransport(): void {
  singleton?.dispose();
  singleton = null;
}
