import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/utils/backend-url", () => ({
  getBackendBaseUrl: () => "https://assist.test/api",
}));

type ListenerMap = Record<string, Array<(event?: MessageEvent<string>) => void>>;

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly url: string;
  readyState = MockWebSocket.CONNECTING;
  readonly sent: string[] = [];
  private readonly listeners: ListenerMap = {};

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (event?: MessageEvent<string>) => void): void {
    this.listeners[type] ??= [];
    this.listeners[type].push(listener);
  }

  send(payload: string): void {
    this.sent.push(payload);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  emitOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    for (const listener of this.listeners.open ?? []) {
      listener();
    }
  }

  emitMessage(payload: unknown): void {
    const event = { data: JSON.stringify(payload) } as MessageEvent<string>;
    for (const listener of this.listeners.message ?? []) {
      listener(event);
    }
  }

  emitClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    for (const listener of this.listeners.close ?? []) {
      listener();
    }
  }
}

describe("ChatWsTransport", () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
    vi.useRealTimers();
    vi.resetModules();
  });

  it("waits for the socket to open before sending requests", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();

    const requestPromise = transport.request("chat.ping");
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0]?.sent).toEqual([]);

    await vi.advanceTimersByTimeAsync(150);
    expect(MockWebSocket.instances[0]?.sent).toEqual([]);

    MockWebSocket.instances[0]?.emitOpen();
    await vi.advanceTimersByTimeAsync(60);
    expect(MockWebSocket.instances[0]?.sent).toHaveLength(1);

    const outbound = JSON.parse(MockWebSocket.instances[0]!.sent[0]!);
    MockWebSocket.instances[0]?.emitMessage({
      id: outbound.id,
      result: { ok: true },
    });

    await expect(requestPromise).resolves.toEqual({ ok: true });
    transport.dispose();
  });

  it("resubscribes conversations from the last delivered event id after reconnect", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();
    const listener = vi.fn();

    transport.subscribeConversation(
      {
        conversationId: "conv_1",
        sinceStreamEventId: 2,
      },
      listener,
    );

    expect(MockWebSocket.instances).toHaveLength(1);
    const firstSocket = MockWebSocket.instances[0]!;
    firstSocket.emitOpen();
    await vi.advanceTimersByTimeAsync(60);

    const firstSubscribe = JSON.parse(firstSocket.sent[0]!);
    expect(firstSubscribe.body).toMatchObject({
      _tag: "chat.stream.subscribe",
      conversationId: "conv_1",
      sinceStreamEventId: 2,
    });
    firstSocket.emitMessage({
      id: firstSubscribe.id,
      result: { conversationId: "conv_1", subscribed: true },
    });
    firstSocket.emitMessage({
      type: "push",
      channel: "chat.streamEvent",
      data: {
        conversationId: "conv_1",
        event: {
          id: 5,
          type: "runtime_update",
          data: { statusLabel: "Thinking" },
        },
      },
    });

    expect(listener).toHaveBeenCalledWith({
      id: 5,
      type: "runtime_update",
      data: { statusLabel: "Thinking" },
    });

    firstSocket.emitClose();
    await vi.advanceTimersByTimeAsync(500);
    expect(MockWebSocket.instances).toHaveLength(2);

    const secondSocket = MockWebSocket.instances[1]!;
    secondSocket.emitOpen();
    await vi.advanceTimersByTimeAsync(60);

    const secondSubscribe = JSON.parse(secondSocket.sent[0]!);
    expect(secondSubscribe.body).toMatchObject({
      _tag: "chat.stream.subscribe",
      conversationId: "conv_1",
      sinceStreamEventId: 5,
    });

    transport.dispose();
  });

  it("resets the replay cursor when the caller rewinds within the same run", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();
    const listener = vi.fn();

    transport.subscribeConversation(
      {
        conversationId: "conv_1",
        sinceStreamEventId: 2,
        runMessageId: "msg_1",
      },
      listener,
    );

    expect(MockWebSocket.instances).toHaveLength(1);
    const socket = MockWebSocket.instances[0]!;
    socket.emitOpen();
    await vi.advanceTimersByTimeAsync(60);

    const firstSubscribe = JSON.parse(socket.sent[0]!);
    socket.emitMessage({
      id: firstSubscribe.id,
      result: { conversationId: "conv_1", subscribed: true },
    });
    socket.emitMessage({
      type: "push",
      channel: "chat.streamEvent",
      data: {
        conversationId: "conv_1",
        event: {
          id: 5,
          type: "runtime_update",
          data: {
            statusLabel: "Thinking",
            runMessageId: "msg_1",
          },
        },
      },
    });

    transport.subscribeConversation(
      {
        conversationId: "conv_1",
        sinceStreamEventId: 0,
        runMessageId: "msg_1",
      },
      vi.fn(),
    );
    await vi.advanceTimersByTimeAsync(60);

    const secondSubscribe = JSON.parse(socket.sent[1]!);
    expect(secondSubscribe.body).toMatchObject({
      _tag: "chat.stream.subscribe",
      conversationId: "conv_1",
      sinceStreamEventId: 0,
      runMessageId: "msg_1",
    });

    transport.dispose();
  });

  it("does not emit a synthetic subscribe failure when the socket closes mid-request and reconnects", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();
    const listener = vi.fn();

    transport.subscribeConversation(
      {
        conversationId: "conv_1",
        sinceStreamEventId: 0,
      },
      listener,
    );

    expect(MockWebSocket.instances).toHaveLength(1);
    const firstSocket = MockWebSocket.instances[0]!;
    firstSocket.emitOpen();
    expect(firstSocket.sent).toHaveLength(1);

    firstSocket.emitClose();
    await vi.advanceTimersByTimeAsync(500);

    expect(MockWebSocket.instances).toHaveLength(2);
    const secondSocket = MockWebSocket.instances[1]!;
    secondSocket.emitOpen();
    await vi.advanceTimersByTimeAsync(60);

    expect(listener).not.toHaveBeenCalledWith(
      expect.objectContaining({
        type: "error",
      }),
    );

    transport.dispose();
  });

  it("does not send a rejected pending request after reconnect", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();

    const requestPromise = transport.request("chat.ping");
    expect(MockWebSocket.instances).toHaveLength(1);

    const firstSocket = MockWebSocket.instances[0]!;
    firstSocket.emitClose();
    await expect(requestPromise).rejects.toThrow("WebSocket connection closed");

    await vi.advanceTimersByTimeAsync(500);
    expect(MockWebSocket.instances).toHaveLength(2);

    const secondSocket = MockWebSocket.instances[1]!;
    secondSocket.emitOpen();
    await vi.advanceTimersByTimeAsync(10);

    expect(firstSocket.sent).toEqual([]);
    expect(secondSocket.sent).toEqual([]);

    transport.dispose();
  });

  it("only emits canonical parsed user lifecycle events", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();
    const listener = vi.fn();

    transport.subscribeUserEvents(listener);
    expect(MockWebSocket.instances).toHaveLength(1);

    const socket = MockWebSocket.instances[0]!;
    socket.emitOpen();

    socket.emitMessage({
      type: "push",
      channel: "chat.userEvent",
      data: {
        type: "stream_registered",
        conversation_id: "conv_1",
      },
    });
    socket.emitMessage({
      type: "push",
      channel: "chat.userEvent",
      data: {
        type: "stream_started",
        conversation_id: "conv_1",
        user_message_id: "msg_1",
        run_id: "run_1",
        current_step: "Starting",
      },
    });

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({
      type: "stream_started",
      conversation_id: "conv_1",
      user_message_id: "msg_1",
      run_id: "run_1",
      status: undefined,
      current_step: "Starting",
      started_at: undefined,
    });

    transport.dispose();
  });

  it("flushes queued requests once in insertion order when the socket opens", async () => {
    const { ChatWsTransport } = await import("./wsTransport");
    const transport = new ChatWsTransport();

    const firstRequest = transport.request("chat.ping");
    const secondRequest = transport.request("chat.stream.cancel", { conversationId: "conv_1" });

    expect(MockWebSocket.instances).toHaveLength(1);
    const socket = MockWebSocket.instances[0]!;
    expect(socket.sent).toEqual([]);

    socket.emitOpen();
    await vi.advanceTimersByTimeAsync(10);

    expect(socket.sent).toHaveLength(2);
    const firstOutbound = JSON.parse(socket.sent[0]!);
    const secondOutbound = JSON.parse(socket.sent[1]!);
    expect(firstOutbound.body._tag).toBe("chat.ping");
    expect(secondOutbound.body).toMatchObject({
      _tag: "chat.stream.cancel",
      conversationId: "conv_1",
    });

    socket.emitMessage({ id: firstOutbound.id, result: { ok: true } });
    socket.emitMessage({ id: secondOutbound.id, result: { status: "cancelled" } });

    await expect(firstRequest).resolves.toEqual({ ok: true });
    await expect(secondRequest).resolves.toEqual({ status: "cancelled" });

    transport.dispose();
  });
});
