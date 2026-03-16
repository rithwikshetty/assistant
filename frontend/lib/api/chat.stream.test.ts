import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StreamTransportEvent } from "@/lib/contracts/chat";

const subscribeConversationMock = vi.fn();
const subscribeUserEventsMock = vi.fn();

vi.mock("@/lib/chat/wsTransport", () => ({
  getChatWsTransport: () => ({
    subscribeConversation: subscribeConversationMock,
    subscribeUserEvents: subscribeUserEventsMock,
  }),
}));

function makeEvent(event: StreamTransportEvent): StreamTransportEvent {
  return event;
}

describe("streamChat transport", () => {
  beforeEach(() => {
    subscribeConversationMock.mockReset();
    subscribeUserEventsMock.mockReset();
  });

  it("yields runtime and terminal events from the shared WebSocket transport", async () => {
    subscribeConversationMock.mockImplementation(
      (
        _options: unknown,
        listener: (event: StreamTransportEvent) => void,
      ) => {
        queueMicrotask(() => {
          listener(
            makeEvent({
              id: 1,
              type: "runtime_update",
              data: {
                statusLabel: "Thinking",
              },
            }),
          );
          listener(
            makeEvent({
              id: 2,
              type: "done",
              data: {
                conversationId: "conv_1",
                runId: null,
                runMessageId: null,
                assistantMessageId: null,
                status: "completed",
                cancelled: false,
                pendingRequests: [],
                usage: null,
                conversationUsage: null,
                elapsedSeconds: null,
                costUsd: null,
              },
            }),
          );
        });
        return () => undefined;
      },
    );

    const { streamChat } = await import("./chat");
    const received: Array<{ type: string; id: number }> = [];
    for await (const event of streamChat("conv_1")) {
      received.push({ type: event.type, id: event.id });
    }

    expect(received).toEqual([
      { type: "runtime_update", id: 1 },
      { type: "done", id: 2 },
    ]);
    expect(subscribeConversationMock).toHaveBeenCalledWith(
      {
        conversationId: "conv_1",
        sinceStreamEventId: 0,
        runMessageId: null,
      },
      expect.any(Function),
    );
  });

  it("forwards transport progress for delivered stream events", async () => {
    const onTransportProgress = vi.fn();

    subscribeConversationMock.mockImplementation(
      (
        _options: unknown,
        listener: (event: StreamTransportEvent) => void,
      ) => {
        queueMicrotask(() => {
          listener(
            makeEvent({
              id: 4,
              type: "runtime_update",
              data: {
                statusLabel: "Thinking",
              },
            }),
          );
          listener(
            makeEvent({
              id: 5,
              type: "done",
              data: {
                conversationId: "conv_2",
                runId: null,
                runMessageId: null,
                assistantMessageId: null,
                status: "completed",
                cancelled: false,
                pendingRequests: [],
                usage: null,
                conversationUsage: null,
                elapsedSeconds: null,
                costUsd: null,
              },
            }),
          );
        });
        return () => undefined;
      },
    );

    const { streamChat } = await import("./chat");
    const received: Array<{ type: string; id: number }> = [];
    for await (const event of streamChat("conv_2", { onTransportProgress })) {
      received.push({ type: event.type, id: event.id });
    }

    expect(onTransportProgress).toHaveBeenNthCalledWith(1, { eventId: 4 });
    expect(onTransportProgress).toHaveBeenNthCalledWith(2, { eventId: 5 });
    expect(received).toEqual([
      { type: "runtime_update", id: 4 },
      { type: "done", id: 5 },
    ]);
  });

  it("unsubscribes when aborted", async () => {
    const unsubscribe = vi.fn();
    let _listenerRef: ((event: StreamTransportEvent) => void) | null = null;

    subscribeConversationMock.mockImplementation(
      (
        _options: unknown,
        listener: (event: StreamTransportEvent) => void,
      ) => {
        _listenerRef = listener;
        return unsubscribe;
      },
    );

    const controller = new AbortController();
    const { streamChat } = await import("./chat");
    const iterator = streamChat("conv_abort", { abortSignal: controller.signal })[Symbol.asyncIterator]();

    controller.abort();
    const result = await iterator.next();

    expect(result.done).toBe(true);
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });
});
