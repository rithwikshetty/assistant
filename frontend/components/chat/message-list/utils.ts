/**
 * Utility functions for message-list components
 */

import {
  FileText, Globe, BookOpen, MagnifyingGlass, FileMagnifyingGlass, ChartBar, ListChecks, CalendarBlank,
  Calculator, UserCircle, Code, Cube,
} from "@phosphor-icons/react";
import {
  getToolDisplayName as getRegistryToolDisplayName,
  getToolGroupKey as getRegistryToolGroupKey,
  getToolIconKey,
  isVisibleToolName,
} from "@/lib/tools/constants";
import type { MessageContentPart, ContentSegment } from "./types";

// ============================================================================
// Visible Tools (render directly)
// These are large visual outputs that should render prominently
// ============================================================================

export const isVisibleTool = (toolName: string): boolean => {
  return isVisibleToolName(toolName);
};

export const isVisibleToolPart = (part: MessageContentPart): boolean => {
  if (part.type !== "tool-call") return false;
  return isVisibleTool(part.toolName);
};

/**
 * Get the grouping key for a tool (consecutive tools with same key get grouped).
 */
export const getToolGroupKey = (toolName: string): string => {
  return getRegistryToolGroupKey(toolName);
};

export const getContentPartStableKey = (part: MessageContentPart, fallbackIndex: number): string => {
  if (part.type === "divider") {
    const itemId = typeof part.itemId === "string" ? part.itemId.trim() : "";
    if (itemId.length > 0) {
      return `divider:${itemId}`;
    }
    const label = typeof part.label === "string" ? part.label.trim() : "";
    return `divider:${label || fallbackIndex}`;
  }

  if (part.type === "tool-call") {
    const callId = part.toolCallId || `${part.toolName}:${fallbackIndex}`;
    return `tool:${callId}`;
  }

  if (part.type === "reasoning") {
    const reasoningId = (part.metadata as { id?: unknown } | undefined)?.id;
    if (typeof reasoningId === "string" && reasoningId.length > 0) {
      return `reasoning:${reasoningId}`;
    }
    const raw = typeof part.rawText === "string"
      ? part.rawText
      : typeof part.text === "string"
        ? part.text
        : "";
    return `reasoning:${part.title || "untitled"}:${raw.slice(0, 48)}:${fallbackIndex}`;
  }

  return `part:${fallbackIndex}`;
};

/**
 * Segment content into text, visible tools, grouped tool calls, and direct parts.
 */
export function segmentContent(content: MessageContentPart[]): ContentSegment[] {
  const result: ContentSegment[] = [];
  let currentToolGroup: { groupKey: string; parts: MessageContentPart[] } | null = null;

  const flushToolGroup = () => {
    if (!currentToolGroup || currentToolGroup.parts.length === 0) return;
    result.push({
      type: "tool-group",
      groupKey: currentToolGroup.groupKey,
      parts: [...currentToolGroup.parts],
    });
    currentToolGroup = null;
  };

  for (const part of content) {
    if (part.type === "text") {
      flushToolGroup();
      if (part.text && part.text.trim()) {
        result.push({ type: "text", text: part.text });
      }
    } else if (part.type === "divider") {
      flushToolGroup();
      result.push({ type: "divider", label: part.label || "Automatically compacting context" });
    } else if (part.type === "tool-call" && isVisibleToolPart(part)) {
      // Visible tools render directly and should not be merged into grouped sessions.
      flushToolGroup();
      result.push({ type: "visible-tool", part });
    } else if (part.type === "tool-call") {
      const groupKey = getToolGroupKey(part.toolName);
      if (currentToolGroup && currentToolGroup.groupKey === groupKey) {
        currentToolGroup.parts.push(part);
      } else {
        flushToolGroup();
        currentToolGroup = { groupKey, parts: [part] };
      }
    } else if (part.type === "reasoning") {
      flushToolGroup();
      const isStreamingReasoning =
        (part.metadata as { streaming?: unknown } | undefined)?.streaming === true;
      // Keep persisted reasoning summaries hidden; only show the live
      // streaming "Thinking..." marker.
      if (!isStreamingReasoning) {
        continue;
      }
      result.push({ type: "part", part });
    } else {
      flushToolGroup();
      result.push({ type: "part", part });
    }
  }
  flushToolGroup();

  return result;
}

// ============================================================================
// Formatting Helpers
// ============================================================================

/**
 * Format duration in milliseconds to human-readable string
 */
export const formatDuration = (ms: number): string => {
  if (Number.isNaN(ms) || !Number.isFinite(ms) || ms <= 0) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 60_000) return `${Math.round(ms / 1000)} s`;
  const minutes = ms / 60000;
  return minutes >= 10 ? `${Math.round(minutes)} min` : `${minutes.toFixed(1)} min`;
};

/**
 * Format runtime for worklog headers (e.g. "17m 14s")
 */
export const formatWorkedDuration = (ms: number): string => {
  if (Number.isNaN(ms) || !Number.isFinite(ms) || ms <= 0) return "0s";
  const totalSeconds = Math.max(1, Math.round(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
};

/**
 * Extract hostname from URL
 */
export const getHost = (url: string): string | null => {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return null;
  }
};

// ============================================================================
// Tool Display Helpers
// ============================================================================

/**
 * Get the appropriate icon for a tool
 */
export function getToolIcon(toolName: string): typeof FileText {
  switch (getToolIconKey(toolName)) {
    case "globe":
      return Globe;
    case "book":
      return BookOpen;
    case "blocks":
      return Cube;
    case "file-search":
      return FileMagnifyingGlass;
    case "search":
      return MagnifyingGlass;
    case "chart":
      return ChartBar;
    case "calendar":
      return CalendarBlank;
    case "tasks":
      return ListChecks;
    case "user-input":
      return UserCircle;
    case "code":
      return Code;
    case "calculator":
      return Calculator;
    default:
      return FileText;
  }
}

/**
 * Get human-readable display name for a tool
 */
export function getToolDisplayName(toolName: string): string {
  return getRegistryToolDisplayName(toolName);
}

// ============================================================================
// Reasoning Text Helpers
// ============================================================================

export const DEFAULT_REASONING_TITLE = "Reasoning summary";
export const THINKING_TITLE = "Thinking";

/**
 * Split reasoning text to extract title and body
 */
export const splitReasoningText = (
  rawText: string,
  providedBody: string,
  providedTitle?: string,
): { title: string; body: string } => {
  const fallbackBody = providedBody && providedBody.trim().length ? providedBody : rawText;
  const normalizedTitle = providedTitle?.trim() ?? "";
  const trimmed = rawText.trim();

  const parseMarkdownHeading = (input: string): { heading: string; body: string } | null => {
    if (!input.startsWith("**")) return null;
    const closing = input.indexOf("**", 2);
    if (closing === -1) return null;
    const heading = input.slice(2, closing).trim();
    const remainder = input.slice(closing + 2);
    const body = remainder.replace(/^\s*\n+/, "").replace(/^\s+/, "");
    return { heading, body };
  };

  const markdownHeading = parseMarkdownHeading(trimmed);

  if (normalizedTitle) {
    let body = fallbackBody || rawText;

    // If backend already provided a title, strip a matching leading markdown
    // heading from the body to avoid rendering the same title twice.
    if (markdownHeading) {
      const headingMatchesProvidedTitle =
        !markdownHeading.heading ||
        markdownHeading.heading.toLowerCase() === normalizedTitle.toLowerCase();
      if (headingMatchesProvidedTitle) {
        body = markdownHeading.body.length ? markdownHeading.body : body;
      }
    }

    return { title: normalizedTitle, body };
  }

  if (markdownHeading) {
    return {
      title: markdownHeading.heading || DEFAULT_REASONING_TITLE,
      body: markdownHeading.body.length ? markdownHeading.body : fallbackBody || rawText,
    };
  }

  return {
    title: normalizedTitle || DEFAULT_REASONING_TITLE,
    body: fallbackBody || trimmed || rawText,
  };
};

// ============================================================================
// CSS Class Constants
// ============================================================================

export const METRIC_CONTAINER_CLASS =
  "flex items-center gap-0.5 type-size-10 font-normal text-muted-foreground/75 whitespace-nowrap leading-none rounded-full bg-muted/30 px-2 py-0.5";

export const METRIC_ITEM_CLASS = "inline-flex items-center gap-0.5 leading-none whitespace-nowrap";
