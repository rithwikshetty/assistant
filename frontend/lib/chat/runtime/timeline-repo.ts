import {
  fetchTimelinePage as fetchTimelinePageApi,
  type RunActivityItemResponse,
  type TimelineItem,
  type TimelineMessagePayload,
  type TimelinePageResponse,
} from "@/lib/api/chat";
import { projectSettledMessageContent, projectStreamContent } from "@/lib/chat/runtime/activity";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import type { Message, MessageContentPart, RunActivityItem } from "@/lib/chat/runtime/types";

export type MessagePage = {
  messages: Message[];
  hasMore: boolean;
  nextCursor: string | null;
};

export function mapActivityItemResponse(item: RunActivityItemResponse): RunActivityItem {
  return {
    id: item.id,
    runId: item.run_id,
    itemKey: item.item_key,
    kind: item.kind,
    status: item.status,
    title: item.title ?? null,
    summary: item.summary ?? null,
    sequence: item.sequence,
    payload: item.payload,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

export function resolveMessageText(message: Message, allowEmptyPayloadText = false): string {
  const rawText = message.metadata?.payload?.text;
  if (typeof rawText === "string" && (allowEmptyPayloadText || rawText.trim().length > 0)) {
    return rawText;
  }

  return message.content.reduce((text, part) => {
    if (part.type !== "text") return text;
    return `${text}${part.text}`;
  }, "");
}

function normalizeLatencyMs(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return Math.round(raw);
  }
  if (typeof raw === "string" && raw.trim().length > 0 && Number.isFinite(Number(raw))) {
    const parsed = Number(raw);
    if (parsed >= 0) return Math.round(parsed);
  }
  return null;
}

export function mapTimelineItem(item: TimelineItem): Message | null {
  const role = item.role === "assistant" || item.role === "user" ? item.role : null;
  const payload: TimelineMessagePayload = item.payload ?? { text: "" };

  if (!role) {
    return null;
  }

  const activityItems: RunActivityItem[] = Array.isArray(item.activity_items)
    ? item.activity_items.map(mapActivityItemResponse)
    : [];

  let contentParts: MessageContentPart[] = [];
  const rawStatus = typeof payload.status === "string" ? payload.status : null;
  const isLiveAssistant =
    item.type === "assistant_message_partial" ||
    rawStatus === "running" ||
    rawStatus === "paused" ||
    rawStatus === "awaiting_input" ||
    rawStatus === "streaming";
  if (role === "assistant") {
    const text = typeof item.text === "string" ? item.text : "";
    contentParts = isLiveAssistant
      ? projectStreamContent({
          draftText: text,
          activityItems,
        })
      : projectSettledMessageContent({
          text,
          activityItems,
        });
  } else if (typeof item.text === "string") {
    contentParts = [{ type: "text", text: item.text }];
  } else {
    contentParts = [{ type: "text", text: "" }];
  }

  const attachmentsMeta =
    role === "user"
      ? payload.attachments ?? undefined
      : undefined;
  const attachments = attachmentsMeta?.map((att: NonNullable<TimelineMessagePayload["attachments"]>[number]) => ({
    id: att.id,
    name: att.original_filename ?? att.filename ?? "Attachment",
    contentType: att.file_type ?? undefined,
    fileSize: att.file_size ?? undefined,
  }));

  let status = rawStatus;
  if (status === "paused") status = "awaiting_input";
  if (status === "running") status = "streaming";
  const responseLatencyMs =
    normalizeLatencyMs(payload.response_latency_ms);
  const finishReasonRaw = payload.finish_reason;
  const finishReason =
    typeof finishReasonRaw === "string" && finishReasonRaw.trim().length > 0
      ? finishReasonRaw.trim()
      : status === "cancelled"
        ? "cancelled"
        : null;
  const checkpointEventId = null;

  return {
    id: item.id,
    role,
    content: contentParts,
    activityItems,
    createdAt: new Date(item.created_at),
    metadata: {
      event_type: item.type,
      payload,
      run_id: item.run_id ?? null,
      activity_item_count: activityItems.length,
      stream_checkpoint_event_id: checkpointEventId,
    },
    status,
    attachments,
    responseLatencyMs,
    finishReason,
    userFeedbackId: null,
    userFeedbackRating: null,
    userFeedbackUpdatedAt: null,
    suggestedQuestions: null,
  };
}

export async function fetchConversationTimelinePage(options: {
  conversationId: string;
  limit: number;
  cursor?: string | null;
}): Promise<MessagePage> {
  const payload: TimelinePageResponse = await fetchTimelinePageApi({
    conversationId: options.conversationId,
    limit: options.limit,
    cursor: options.cursor ?? null,
  });

  const items = Array.isArray(payload.items) ? payload.items : [];
  const mapped = items.map(mapTimelineItem).filter((item): item is Message => item !== null);

  return {
    messages: mapped,
    hasMore: Boolean(payload.has_more),
    nextCursor: payload.next_cursor ?? null,
  };
}

export function findLatestAssistantMessage(messages: Message[]): Message | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") return messages[i];
  }
  return null;
}

export function findLatestAssistantMessageForRun(messages: Message[], runId?: string | null): Message | null {
  const normalizedRunId = normalizeNonEmptyString(runId);
  if (!normalizedRunId) return null;

  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "assistant") continue;
    if (resolveRunIdFromMessage(message) === normalizedRunId) return message;
  }
  return null;
}

export function resolveRunIdFromMessage(message: Message | null): string | null {
  if (!message) return null;
  return normalizeNonEmptyString(message.metadata?.run_id);
}

export function cloneContentPart(part: MessageContentPart): MessageContentPart {
  try {
    return JSON.parse(JSON.stringify(part)) as MessageContentPart;
  } catch {
    return { ...part };
  }
}

export { normalizeNonEmptyString } from "@/lib/utils/normalize";
