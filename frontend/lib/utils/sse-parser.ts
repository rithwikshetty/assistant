/**
 * SSE Parser Utility
 *
 * Minimal SSE parser for lines formatted as per text/event-stream.
 * Aggregates multi-line `data:` payloads and returns the decoded JSON objects.
 */

// ============================================================================
// Types
// ============================================================================

export type SseEvent = {
  id?: number;
  type?: string;
  data?: unknown;
  content?: unknown;
  __sse?: {
    idRaw?: string;
    eventType?: string;
    retryMs?: number;
  };
};

type SseControlFields = {
  idRaw?: string;
  eventType?: string;
  retryMs?: number;
};

type ParsedSseBlock = {
  dataPayload: string | null;
  control: SseControlFields;
};

// ============================================================================
// SSE Parsing
// ============================================================================

function parseSseControlAndData(block: string): ParsedSseBlock {
  const lines = block.split("\n");
  const dataLines: string[] = [];
  const control: SseControlFields = {};

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line || line.startsWith(":")) continue;
    const separatorIndex = line.indexOf(":");
    const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line;
    let value = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : "";
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }

    if (field === "data") {
      dataLines.push(value);
      continue;
    }
    if (field === "id") {
      control.idRaw = value;
      continue;
    }
    if (field === "event") {
      const normalizedEvent = value.trim();
      if (normalizedEvent) {
        control.eventType = normalizedEvent;
      }
      continue;
    }
    if (field === "retry") {
      const retryMs = Number.parseInt(value, 10);
      if (Number.isFinite(retryMs) && retryMs > 0) {
        control.retryMs = retryMs;
      }
    }
  }

  if (!dataLines.length) {
    return { dataPayload: null, control };
  }
  return { dataPayload: dataLines.join("\n").trim(), control };
}

function attachSseControlFields<TEvent>(parsedEvent: TEvent, control: SseControlFields): TEvent {
  if (!parsedEvent || typeof parsedEvent !== "object" || Array.isArray(parsedEvent)) {
    return parsedEvent;
  }

  const eventRecord = parsedEvent as Record<string, unknown>;
  if (eventRecord.type == null && control.eventType) {
    eventRecord.type = control.eventType;
  }
  if (eventRecord.id == null && control.idRaw) {
    const parsedId = Number.parseInt(control.idRaw, 10);
    if (Number.isFinite(parsedId) && parsedId >= 0) {
      eventRecord.id = parsedId;
    }
  }
  if (control.idRaw || control.eventType || control.retryMs) {
    Object.defineProperty(eventRecord, "__sse", {
      value: {
        idRaw: control.idRaw,
        eventType: control.eventType,
        retryMs: control.retryMs,
      },
      enumerable: false,
      writable: false,
      configurable: true,
    });
  }
  return parsedEvent;
}

export function parseSseEventBlock<TEvent = SseEvent>(block: string): TEvent | null {
  const parsedBlock = parseSseControlAndData(block);
  if (!parsedBlock.dataPayload) return null;

  try {
    const parsed = JSON.parse(parsedBlock.dataPayload) as TEvent;
    return attachSseControlFields(parsed, parsedBlock.control);
  } catch {
    return null;
  }
}

/**
 * Minimal SSE parser for lines formatted as per text/event-stream.
 * Aggregates multi-line `data:` payloads and returns the decoded JSON objects.
 */
export async function* parseSse<TEvent = SseEvent>(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  abortSignal: AbortSignal
): AsyncGenerator<TEvent, void, unknown> {
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    if (abortSignal.aborted) return;
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Normalize line endings so CRLF/LF framed streams are handled uniformly.
    buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const evt = parseSseEventBlock<TEvent>(part);
      if (evt) yield evt;
    }
  }

  if (buffer.trim()) {
    const evt = parseSseEventBlock<TEvent>(buffer);
    if (evt) yield evt;
  }
}
