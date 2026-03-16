import { describe, expect, it } from "vitest";
import { parseSse, parseSseEventBlock, type SseEvent } from "./sse-parser";

function makeReader(chunks: string[]): ReadableStreamDefaultReader<Uint8Array> {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return stream.getReader();
}

describe("sse-parser", () => {
  it("parses an SSE event block with multiple data lines", () => {
    const parsed = parseSseEventBlock<SseEvent>("data: {\"a\": 1,\ndata: \"b\": 2}");
    expect(parsed).toEqual({ a: 1, b: 2 });
  });

  it("parses CRLF framed events", async () => {
    const reader = makeReader([
      "data: {\"id\":1,\"type\":\"message\"}\r\n\r\n",
      "data: {\"id\":2,\"type\":\"done\"}\r\n\r\n",
    ]);
    const abortController = new AbortController();

    const events: SseEvent[] = [];
    for await (const event of parseSse<SseEvent>(reader, abortController.signal)) {
      events.push(event);
    }

    expect(events).toEqual([
      { id: 1, type: "message" },
      { id: 2, type: "done" },
    ]);
  });

  it("parses events split across chunk boundaries", async () => {
    const reader = makeReader([
      "data: {\"id\": 3, \"type\": \"mess",
      "age\", \"data\": {\"ok\": true}}\n",
      "\n",
    ]);
    const abortController = new AbortController();

    const events: SseEvent[] = [];
    for await (const event of parseSse<SseEvent>(reader, abortController.signal)) {
      events.push(event);
    }

    expect(events).toEqual([{ id: 3, type: "message", data: { ok: true } }]);
  });

  it("maps event/id/retry control fields onto parsed payload", () => {
    const parsed = parseSseEventBlock<SseEvent>(
      "id: 42\nevent: heartbeat\nretry: 1750\ndata: {\"data\": {\"alive\": true}}",
    );

    expect(parsed).toEqual({
      id: 42,
      type: "heartbeat",
      data: { alive: true },
    });
    expect(parsed?.__sse).toEqual({
      idRaw: "42",
      eventType: "heartbeat",
      retryMs: 1750,
    });
  });

  it("ignores keepalive and invalid json blocks", async () => {
    const reader = makeReader([
      ": keepalive\n\n",
      "data: not-json\n\n",
      "data: {\"id\": 4, \"type\": \"message\"}\n\n",
    ]);
    const abortController = new AbortController();

    const events: SseEvent[] = [];
    for await (const event of parseSse<SseEvent>(reader, abortController.signal)) {
      events.push(event);
    }

    expect(events).toEqual([{ id: 4, type: "message" }]);
  });

  it("ignores control-only blocks without data payload", () => {
    const parsed = parseSseEventBlock<SseEvent>("retry: 2000\nid: 5\nevent: heartbeat");
    expect(parsed).toBeNull();
  });
});
