import type { ChatMessageContentPart, ContentPhase } from "@/lib/chat/content-parts";
import {
  parseToolRequestPayloadForTool,
  parseToolResultPayloadForTool,
} from "@/lib/contracts/chat-tool-payloads";
import { normalizeNonEmptyString } from "@/lib/utils/normalize";
import type { RunActivityItem } from "@/lib/chat/runtime/types";

function normalizeToolName(raw: unknown): string | undefined {
  return normalizeNonEmptyString(raw) ?? undefined;
}

function normalizeToolCallId(raw: unknown): string | undefined {
  return normalizeNonEmptyString(raw) ?? undefined;
}

function parseTypedPayloadRecord(args: {
  toolName: string;
  raw: unknown;
  kind: "request" | "result";
}): Record<string, unknown> | undefined {
  const { toolName, raw, kind } = args;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }

  try {
    return (
      kind === "request"
        ? parseToolRequestPayloadForTool(toolName, raw, `activity.${kind}`)
        : parseToolResultPayloadForTool(toolName, raw, `activity.${kind}`)
    ) as Record<string, unknown>;
  } catch {
    return undefined;
  }
}

function normalizeNonNegativeInt(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return Math.max(0, Math.floor(raw));
  }
  if (typeof raw === "string" && raw.trim().length > 0) {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) {
      return Math.max(0, Math.floor(parsed));
    }
  }
  return null;
}

function clientItemId(itemKey: string): string {
  return `client:${itemKey}`;
}

function sortActivityItems(items: RunActivityItem[]): RunActivityItem[] {
  return [...items].sort((left, right) => {
    if (left.sequence !== right.sequence) {
      return left.sequence - right.sequence;
    }
    const leftPosition = readActivityPosition(left);
    const rightPosition = readActivityPosition(right);
    if (leftPosition != null && rightPosition != null && leftPosition !== rightPosition) {
      return leftPosition - rightPosition;
    }
    return left.itemKey.localeCompare(right.itemKey);
  });
}

function upsertActivityItem(items: RunActivityItem[], activityItem: RunActivityItem): RunActivityItem[] {
  const next = [...items];
  const index = next.findIndex((item) => item.itemKey === activityItem.itemKey);
  if (index >= 0) {
    next[index] = activityItem;
  } else {
    next.push(activityItem);
  }
  return sortActivityItems(next);
}

function toolStatusFromPayload(
  result: unknown,
  hasError: boolean,
): RunActivityItem["status"] {
  if (hasError) return "failed";
  if (result && typeof result === "object" && !Array.isArray(result)) {
    const status = normalizeNonEmptyString((result as Record<string, unknown>).status)?.toLowerCase();
    if (status === "pending" || status === "running") return "running";
    if (status === "cancelled") return "cancelled";
    if (status === "error" || status === "failed") return "failed";
    if (status === "completed") return "completed";
  }
  return "running";
}

function toolSummaryFromPayload(args: {
  query?: string | null;
  result?: unknown;
  error?: unknown;
}): string | null {
  if (args.query && args.query.trim()) return args.query.trim();
  if (typeof args.error === "string" && args.error.trim()) return args.error.trim();
  if (args.result && typeof args.result === "object" && !Array.isArray(args.result)) {
    const record = args.result as Record<string, unknown>;
    const summary =
      normalizeNonEmptyString(record.status_label) ??
      normalizeNonEmptyString(record.summary) ??
      normalizeNonEmptyString(record.message);
    if (summary) return summary;
  }
  return null;
}

function mergeToolPayload(args: {
  existing?: RunActivityItem | null;
  toolCallId: string;
  toolName: string;
  sequence: number;
  position?: number | null;
  patch?: Record<string, unknown>;
  summary?: string | null;
  status?: RunActivityItem["status"] | null;
}): RunActivityItem {
  const { existing, toolCallId, toolName, sequence, position, patch, summary, status } = args;
  const itemKey = `tool:${toolCallId}`;
  const basePayload =
    existing?.payload && typeof existing.payload === "object" && !Array.isArray(existing.payload)
      ? { ...existing.payload }
      : {};
  const payload: Record<string, unknown> = {
    ...basePayload,
    tool_call_id: toolCallId,
    tool_name: toolName,
    ...(patch ?? {}),
  };
  if (normalizeNonNegativeInt(basePayload.position) == null && position != null) {
    payload.position = position;
  }

  const nextStatus = status ?? toolStatusFromPayload(payload.result, payload.error != null);
  const nextSummary =
    summary ??
    toolSummaryFromPayload({
      query: normalizeNonEmptyString(payload.query),
      result: payload.result,
      error: payload.error,
    });

  return {
    id: existing?.id ?? clientItemId(itemKey),
    runId: existing?.runId ?? "",
    itemKey,
    kind: "tool",
    status: nextStatus,
    title: toolName.replace(/_/g, " "),
    summary: nextSummary,
    sequence: existing?.sequence ?? sequence,
    payload,
    createdAt: existing?.createdAt ?? new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function findActivityItem(items: RunActivityItem[], itemKey: string): RunActivityItem | null {
  return items.find((item) => item.itemKey === itemKey) ?? null;
}

function interactiveUserInputCallIds(items: RunActivityItem[]): Set<string> {
  const callIds = new Set<string>();
  for (const item of items) {
    if (item.kind !== "user_input") continue;
    const toolCallId = normalizeNonEmptyString(item.payload.tool_call_id);
    if (toolCallId) {
      callIds.add(toolCallId);
    }
  }
  return callIds;
}

type ProjectedActivityPart = {
  part: ChatMessageContentPart;
  position: number | null;
};

function readActivityPosition(item: RunActivityItem): number | null {
  return normalizeNonNegativeInt(item.payload.position);
}

function isWordChar(value: string): boolean {
  return /[A-Za-z0-9'_]/.test(value);
}

function normalizeMarkerPosition(args: {
  text: string;
  rawPosition: number;
  cursor: number;
}): number {
  const { text, rawPosition, cursor } = args;
  if (!text) return 0;

  let position = Math.max(cursor, Math.min(text.length, Math.floor(rawPosition)));
  if (position <= 0 || position >= text.length) {
    return position;
  }

  const left = text[position - 1];
  const right = text[position];
  if (!(isWordChar(left) && isWordChar(right))) {
    return position;
  }

  while (position < text.length && isWordChar(text[position])) {
    position += 1;
  }

  return position;
}

function projectActivityItem(item: RunActivityItem, userInputCallIds: Set<string>): ProjectedActivityPart | null {
  if (item.kind === "tool") {
    const toolCallId = normalizeToolCallId(item.payload.tool_call_id);
    const toolName = normalizeToolName(item.payload.tool_name ?? item.title);
    if (!toolCallId || !toolName) {
      return null;
    }
    if (userInputCallIds.has(toolCallId)) {
      return null;
    }
    const argsValue =
      item.payload.arguments && typeof item.payload.arguments === "object" && !Array.isArray(item.payload.arguments)
        ? item.payload.arguments as Record<string, unknown>
        : undefined;
    const query = normalizeNonEmptyString(item.payload.query);
    const args = query
      ? {
          ...(argsValue ?? {}),
          query,
        }
      : argsValue;
    const result = item.payload.error ?? parseTypedPayloadRecord({
      toolName,
      raw: item.payload.result,
      kind: "result",
    });
    return {
      part: {
        type: "tool-call",
        toolCallId,
        toolName,
        args,
        result,
        isError: item.payload.error != null || item.status === "failed",
        phase: "worklog",
      },
      position: readActivityPosition(item),
    };
  }

  if (item.kind === "user_input") {
    const toolCallId = normalizeToolCallId(item.payload.tool_call_id);
    const toolName = normalizeToolName(item.payload.tool_name ?? item.title);
    if (!toolCallId || !toolName) {
      return null;
    }
    const request = parseTypedPayloadRecord({
      toolName,
      raw: item.payload.request,
      kind: "request",
    });
    const result = parseTypedPayloadRecord({
      toolName,
      raw: item.payload.result,
      kind: "result",
    });
    return {
      part: {
        type: "tool-call",
        toolCallId,
        toolName,
        args: request,
        result,
        isError: item.payload.error != null || item.status === "failed",
        phase: "worklog",
      },
      position: readActivityPosition(item),
    };
  }

  if (item.kind === "reasoning") {
    const title = normalizeNonEmptyString(item.title) ?? "Thinking";
    const rawText = normalizeNonEmptyString(item.payload.raw_text) ?? "";
    return {
      part: {
        type: "reasoning",
        title,
        text: normalizeNonEmptyString(item.summary) ?? (rawText || title),
        rawText: rawText || undefined,
        phase: "worklog",
      },
      position: readActivityPosition(item),
    };
  }

  if (item.kind === "compaction") {
    return {
      part: {
        type: "divider",
        label: normalizeNonEmptyString(item.payload.label) ?? normalizeNonEmptyString(item.title) ?? "Automatically compacting context",
        source: normalizeNonEmptyString(item.payload.source) ?? undefined,
        itemId: normalizeNonEmptyString(item.payload.item_id) ?? undefined,
        phase: "worklog",
      },
      position: readActivityPosition(item),
    };
  }

  return null;
}

function buildOrderedContent(args: {
  text: string;
  activityItems: RunActivityItem[];
}): ChatMessageContentPart[] {
  const { text, activityItems } = args;
  const userInputCallIds = interactiveUserInputCallIds(activityItems);
  const projectedItems = sortActivityItems(activityItems)
    .map((item) => projectActivityItem(item, userInputCallIds))
    .filter((entry): entry is ProjectedActivityPart => entry !== null);

  if (projectedItems.length === 0) {
    return text.length > 0 ? [{ type: "text", text, phase: "final" }] : [];
  }

  const content: ChatMessageContentPart[] = [];
  let cursor = 0;

  for (const entry of projectedItems) {
    const position =
      entry.position != null
        ? normalizeMarkerPosition({
            text,
            rawPosition: entry.position,
            cursor,
          })
        : cursor;

    if (position > cursor) {
      const chunk = text.slice(cursor, position);
      if (chunk) {
        content.push({
          type: "text",
          text: chunk,
        });
      }
      cursor = position;
    }

    content.push(entry.part);
  }

  if (cursor < text.length || content.length === 0) {
    const trailing = text.slice(cursor);
    if (trailing || content.length === 0) {
      content.push({
        type: "text",
        text: trailing || text,
      });
    }
  }

  let lastProcessIndex = -1;
  for (let index = 0; index < content.length; index += 1) {
    if (content[index].type !== "text") {
      lastProcessIndex = index;
    }
  }

  return content
    .map((part, index) => {
      if (part.type !== "text") {
        const phase: ContentPhase = part.phase ?? "worklog";
        return { ...part, phase };
      }
      const phase: ContentPhase = lastProcessIndex >= 0 && index <= lastProcessIndex ? "worklog" : "final";
      return {
        ...part,
        phase,
      };
    })
    .filter((part) => part.type !== "text" || part.text.length > 0);
}

export function applyOptimisticToolResultToActivityItems(args: {
  activityItems: RunActivityItem[];
  toolCallId: string;
  result: Record<string, unknown>;
}): RunActivityItem[] | null {
  const { activityItems, toolCallId, result } = args;
  const existing = findActivityItem(activityItems, `tool:${toolCallId}`);
  if (!existing) return null;
  return upsertActivityItem(activityItems, mergeToolPayload({
    existing,
    toolCallId,
    toolName: normalizeToolName(existing.payload.tool_name ?? existing.title) ?? "tool",
    sequence: existing.sequence,
    patch: { result },
    status: toolStatusFromPayload(result, false),
  }));
}

export function projectStreamContent(args: {
  draftText: string;
  activityItems: RunActivityItem[];
}): ChatMessageContentPart[] {
  const { draftText, activityItems } = args;
  const ordered = buildOrderedContent({
    text: draftText,
    activityItems,
  });

  const lastPart = ordered[ordered.length - 1];
  if (
    lastPart &&
    lastPart.type === "text" &&
    lastPart.phase === "final"
  ) {
    const trimmed = lastPart.text.trim();
    const wordCount = trimmed.length > 0 ? trimmed.split(/\s+/).length : 0;
    const hasTerminalPunctuation = /[.!?:…)]$/.test(trimmed);
    if (wordCount === 1 && trimmed.length < 4 && !hasTerminalPunctuation) {
      return ordered.slice(0, -1);
    }
  }

  return ordered;
}

export function projectSettledMessageContent(args: {
  text: string;
  activityItems: RunActivityItem[];
}): ChatMessageContentPart[] {
  const { text, activityItems } = args;
  if (activityItems.length === 0) {
    return [{ type: "text", text }];
  }

  return buildOrderedContent({
    text,
    activityItems,
  });
}
