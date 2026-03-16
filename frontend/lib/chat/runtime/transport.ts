import { streamChat, type StreamEvent } from "@/lib/api/chat";

export type RunChatStreamTransportOptions = {
  sinceStreamEventId?: number;
  runMessageId?: string | null;
  abortSignal: AbortSignal;
  onTransportProgress?: (progress: { eventId: number | null }) => void;
  onEvent: (event: StreamEvent) => Promise<void> | void;
};

export async function runChatStreamTransport(
  conversationId: string,
  options: RunChatStreamTransportOptions,
): Promise<void> {
  const { sinceStreamEventId = 0, runMessageId = null, abortSignal, onTransportProgress, onEvent } = options;
  for await (const event of streamChat(conversationId, {
    sinceStreamEventId,
    runMessageId,
    abortSignal,
    onTransportProgress,
  })) {
    if (abortSignal.aborted) return;
    await onEvent(event);
  }
}
