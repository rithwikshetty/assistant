
/**
 * ChatView - Backend-Driven Chat Interface
 *
 * Features:
 * - MessageList for displaying conversation history
 * - Unified assistant rows for live and settled responses
 * - ChatInput for input
 * - Follow-up suggestions
 * - Memory warning banner
 * - Scroll-to-bottom button
 * - Feedback lock UI
 *
 * The backend is the single source of truth for all message state.
 */

import { type FC, useCallback, useState, useEffect, useRef, useMemo, type DragEvent, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { useChat } from "@/hooks/use-chat";
import { MessageList } from "@/components/chat/message-list";
import { Button } from "@/components/ui/button";
import {
  Warning,
  SpinnerGap,
  Lightbulb,
  ArrowDown,
  ThumbsUp,
  ThumbsDown,
} from "@phosphor-icons/react";
import { CollapsibleInlineList } from "@/components/ui/collapsible-inline-list";
import { useToast } from "@/components/ui/toast";
import { useAutoGenerateTitle } from "@/hooks/useAutoGenerateTitle";
import { generateMessageSuggestions, SuggestionsApiError } from "@/lib/api/suggestions";
import { useAuth } from "@/contexts/auth-context";
import { resolveContextTokensUsed } from "@/lib/chat/context-usage";
import {
  deriveViewportScrollState,
  resolveInitialScrollDecision,
  shouldPreservePinnedBottomOnScroll,
} from "@/lib/chat/scroll-state";
import type { ConversationContextUsage } from "@/lib/api/auth";
import { MessageFeedbackDialog } from "@/components/feedback/message-feedback-dialog";
import type { MessageFeedbackRating } from "@/lib/api/feedback";
import { useFileDrop } from "@/contexts/file-drop-context";
import { FileDropOverlay } from "@/components/chat/file-drop-overlay";
import {
  useConversationInputGate,
  useConversationQueuedTurns,
  useConversationRuntimeManager,
  useConversationStream,
  useConversationStreamMeta,
} from "@/contexts/active-streams-context";
import { resolveStreamPresence } from "@/hooks/use-chat-runtime-display";
import { resolveMessageText } from "@/lib/chat/runtime/timeline-repo";

// Show the context notice at ~80% of the backend's compact trigger threshold.
// e.g. if compaction fires at 57% of the context window, the notice appears at ~45%.
const COMPACT_WARNING_RATIO = 0.8;

// Scroll distance (px) from the top at which to trigger loading older messages.
const SCROLL_NEAR_TOP_PX = 160;

// Ignore sub-pixel scroll corrections to avoid layout-jitter from rounding.
const SCROLL_SUBPIXEL_THRESHOLD = 0.5;

// ============================================================================
// Types
// ============================================================================

/** Bridge that exposes ChatView's send/cancel to a persistent composer above */
export type ComposerBridge = {
      sendMessage: (
        content: string,
        opts: {
          attachmentIds: string[];
          attachments: Array<{ id: string; name: string; contentType?: string; fileSize?: number }>;
        }
      ) => Promise<void>;
  isStreaming: boolean;
  /** false when canEdit=false or feedbackLock=true — parent should hide input */
  inputVisible: boolean;
  /** True when the stream is paused awaiting structured user input */
  isPausedForInput: boolean;
  /** Payload for the paused input overlay, if paused */
  pausedInputPayload: import("@/hooks/use-chat").UserInputPayload | null;
  /** Resume a paused stream immediately after user-input submission */
  resumePausedStream: () => void;
  /** Conversation ID for the current chat */
  conversationId: string;
};

export type ChatViewProps = {
  conversationId: string;
  /** Project ID if this conversation belongs to a project */
  projectId?: string;
  /** Whether the viewer owns this conversation */
  viewerIsOwner?: boolean;
  /** Whether the viewer can edit (send messages) */
  canEdit?: boolean;
  /** Whether feedback is required before continuing */
  requiresFeedback?: boolean;
  /** Context usage for memory warning */
  contextUsage?: ConversationContextUsage | null;
  /** Current conversation title for title-generation gating */
  conversationTitle?: string | null;
  /** Whether redaction is enabled for file uploads */
  redactionEnabled?: boolean;
  /** Callback when redaction setting changes */
  onRedactionChange?: (value: boolean) => void;
  /** Callback to register composer bridge (persistent input pattern) */
  onComposerBridge?: (bridge: ComposerBridge | null) => void;
  /** Callback to push a ReactNode into the persistent composer's topContent slot */
  onComposerTopSlot?: (node: ReactNode) => void;
  /** Custom class name */
  className?: string;
};

// ============================================================================
// ChatView Component
// ============================================================================

export const ChatView: FC<ChatViewProps> = ({
  conversationId,
  projectId: _projectId,
  viewerIsOwner = true,
  canEdit = true,
  requiresFeedback = false,
  contextUsage,
  conversationTitle,
  redactionEnabled: _redactionEnabled = false,
  onRedactionChange: _onRedactionChange,
  onComposerBridge,
  onComposerTopSlot,
  className,
}) => {
  const { user } = useAuth();
  const { addToast } = useToast();
  const isAdmin = (user?.role || "").toUpperCase() === "ADMIN";
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const isUserAtBottomRef = useRef(true); // Track if user is at bottom for smart auto-scroll
  const shouldAutoFollowRef = useRef(true);
  const lastObservedScrollTopRef = useRef(0);
  const touchStartYRef = useRef<number | null>(null);
  const prependAnchorRef = useRef<{
    messageId: string | null;
    topOffset: number;
    previousHeight: number;
    previousTop: number;
  } | null>(null);
  const prependRestoreFrameRef = useRef(0);

  // File drag-and-drop state
  const { isDragging, setIsDragging, onFilesDropped } = useFileDrop();
  const dragCounterRef = useRef(0);
  const dragCancelledRef = useRef(false);
  
  // Feedback lock state (admins are never locked)
  const [feedbackLock, setFeedbackLock] = useState(isAdmin ? false : requiresFeedback);
  const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
  const [feedbackRating, setFeedbackRating] = useState<MessageFeedbackRating | null>(null);
  const [feedbackTargetMessageId, setFeedbackTargetMessageId] = useState<string | null>(null);
  
  // Follow-up suggestions state
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[] | null>(null);
  const [isGeneratingSuggestions, setIsGeneratingSuggestions] = useState(false);
  const [isSuggestionsExpanded, setIsSuggestionsExpanded] = useState(true);
  const suggestionsForMessageIdRef = useRef<string | null>(null);

  // Use our backend-driven chat hook
  const chat = useChat({
    conversationId,
    onError: (error) => {
      console.error("[ChatView] Error:", error);
    },
  });
  const liveStream = useConversationStream(conversationId);
  const inputGate = useConversationInputGate(conversationId);
  const queuedTurns = useConversationQueuedTurns(conversationId);
  const streamMeta = useConversationStreamMeta(conversationId);
  const runtimeManager = useConversationRuntimeManager();
  const isPausedForInput = inputGate.isPausedForInput;
  const pausedInputPayload = inputGate.pausedPayload;
  const queuedTranscriptMessageIds = useMemo(() => {
    return new Set(
      queuedTurns
        .map((queuedTurn) => queuedTurn.userMessageId)
        .filter((messageId): messageId is string => typeof messageId === "string" && messageId.length > 0),
    );
  }, [queuedTurns]);
  const visibleTimeline = useMemo(() => {
    if (queuedTranscriptMessageIds.size === 0) {
      return chat.timeline;
    }
    return chat.timeline.filter((message) => !queuedTranscriptMessageIds.has(message.id));
  }, [chat.timeline, queuedTranscriptMessageIds]);
  const isStreaming = useMemo(() => {
    return resolveStreamPresence({
      stream: streamMeta,
      messages: visibleTimeline,
      isPausedForInput,
    });
  }, [visibleTimeline, isPausedForInput, streamMeta]);
  const chatError = chat.paging.error ?? streamMeta.error;

  useEffect(() => {
    if (!streamMeta.error) return;
    console.error("[ChatView] Error:", streamMeta.error);
  }, [streamMeta.error]);

  // Auto-generate title for new conversations
  useAutoGenerateTitle(conversationId, conversationTitle);
  
  // Update feedback lock when requiresFeedback changes
  useEffect(() => {
    setFeedbackLock(isAdmin ? false : requiresFeedback);
  }, [requiresFeedback, isAdmin]);
  
  // Listen for feedback status events
  useEffect(() => {
    if (!conversationId) return;
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ conversationId: string; requiresFeedback: boolean }>).detail;
      if (!detail || detail.conversationId !== conversationId) return;
      setFeedbackLock(isAdmin ? false : detail.requiresFeedback);
    };
    window.addEventListener("frontend:conversationFeedbackStatus", handler as EventListener);
    return () => window.removeEventListener("frontend:conversationFeedbackStatus", handler as EventListener);
  }, [conversationId, isAdmin]);
  
  // Calculate memory usage percentage from live token counting.
  const memoryPercent = useMemo(() => {
    if (!contextUsage) return null;
    const maxTokens = contextUsage.max_context_tokens ?? null;
    if (!maxTokens || maxTokens <= 0) return null;
    const usedTokensRaw = resolveContextTokensUsed(contextUsage);
    if (usedTokensRaw === null) return null;
    const usedTokens = Math.min(usedTokensRaw, maxTokens);
    return Math.min(100, Math.max(0, Math.round((usedTokens / maxTokens) * 100)));
  }, [contextUsage]);

  // Show a passive context notice when usage reaches ~80% of the compact trigger.
  const showMemoryWarning = useMemo(() => {
    if (!contextUsage || memoryPercent === null) return false;
    const maxTokens = contextUsage.max_context_tokens;
    const compactTrigger = contextUsage.compact_trigger_tokens;
    if (!maxTokens || maxTokens <= 0 || !compactTrigger || compactTrigger <= 0) return false;
    const warningTokens = compactTrigger * COMPACT_WARNING_RATIO;
    const usedTokens = resolveContextTokensUsed(contextUsage) ?? 0;
    return usedTokens >= warningTokens;
  }, [contextUsage, memoryPercent]);
  
  const lastAssistantMessageContext = useMemo((): { messageId: string | null; feedbackMessageId: string | null } => {
    const messages = visibleTimeline;
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role === "assistant") {
        return {
          messageId: msg.id,
          feedbackMessageId: msg.id,
        };
      }
    }
    return {
      messageId: null,
      feedbackMessageId: null,
    };
  }, [visibleTimeline]);

  const lastAssistantMessageId = lastAssistantMessageContext.messageId;
  const lastAssistantFeedbackMessageId = lastAssistantMessageContext.feedbackMessageId;

  // Generate follow-up suggestions
  const handleGenerateSuggestions = useCallback(async () => {
    if (!conversationId || isGeneratingSuggestions) return;
    const messageId = lastAssistantMessageId;
    if (!messageId) return;

    setIsGeneratingSuggestions(true);
    try {
      const result = await generateMessageSuggestions(conversationId, messageId);
      if (result.suggestions && result.suggestions.length > 0) {
        suggestionsForMessageIdRef.current = messageId;
        setSuggestedQuestions(result.suggestions);
        setIsSuggestionsExpanded(true);
      }
    } catch (error) {
      console.error("[ChatView] Failed to generate suggestions:", error);
      if (error instanceof SuggestionsApiError && error.status === 409) {
        addToast({
          type: "info",
          title: "Suggestions unavailable right now",
          description: error.detail || "Suggestions are not available for this message yet.",
        });
      } else {
        addToast({
          type: "error",
          title: "Failed to generate suggestions",
          description: error instanceof Error ? error.message : "Please try again.",
        });
      }
    } finally {
      setIsGeneratingSuggestions(false);
    }
  }, [addToast, conversationId, isGeneratingSuggestions, lastAssistantMessageId]);

  // Clear suggestions when conversation changes or new message is sent
  useEffect(() => {
    setSuggestedQuestions(null);
    suggestionsForMessageIdRef.current = null;
  }, [conversationId]);

  // Handle send message
  const handleSend = useCallback(
    async (
      content: string,
      options: {
        attachmentIds: string[];
        attachments: Array<{ id: string; name: string; contentType?: string; fileSize?: number }>;
      }
    ) => {
      // Clear suggestions when sending
      setSuggestedQuestions(null);
      suggestionsForMessageIdRef.current = null;
      // Enable auto-scroll and scroll to bottom when sending
      isUserAtBottomRef.current = true;
      shouldAutoFollowRef.current = true;
      if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollTo({
          top: scrollContainerRef.current.scrollHeight,
          behavior: "instant",
        });
        lastObservedScrollTopRef.current = scrollContainerRef.current.scrollTop;
      }
      await chat.actions.sendMessage(content, {
        attachmentIds: options.attachmentIds,
        attachments: options.attachments,
      });
    },
    [chat.actions]
  );

  // Keep bridge callbacks stable while always calling the latest handlers.
  const sendMessageRef = useRef(handleSend);
  const resumePausedRef = useRef(() => runtimeManager.handleInteractiveToolSubmitted(conversationId));
  sendMessageRef.current = handleSend;
  resumePausedRef.current = () => runtimeManager.handleInteractiveToolSubmitted(conversationId);

  const bridgeSendMessage = useCallback<ComposerBridge["sendMessage"]>((content, options) => {
    return sendMessageRef.current(content, options);
  }, []);

  const bridgeResumePaused = useCallback<ComposerBridge["resumePausedStream"]>(() => {
    resumePausedRef.current();
  }, []);

  // Register composer bridge for persistent input pattern
  useEffect(() => {
    if (!onComposerBridge) return;
    const inputVisible = canEdit && !feedbackLock;
    onComposerBridge({
      sendMessage: bridgeSendMessage,
      resumePausedStream: bridgeResumePaused,
      isStreaming,
      inputVisible,
      isPausedForInput,
      pausedInputPayload,
      conversationId,
    });
  }, [
    onComposerBridge,
    bridgeSendMessage,
    bridgeResumePaused,
    isStreaming,
    canEdit,
    feedbackLock,
    conversationId,
    isPausedForInput,
    pausedInputPayload,
  ]);

  useEffect(() => {
    if (!onComposerBridge) return;
    return () => onComposerBridge(null);
  }, [onComposerBridge]);

  // Handle suggestion click
  const handleSuggestionClick = useCallback((suggestion: string) => {
    // Focus input and set text
    setIsSuggestionsExpanded(false);
    setTimeout(() => {
      const el = document.querySelector<HTMLTextAreaElement>('textarea');
      if (el) {
        // Set the value directly
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype,
          'value'
        )?.set;
        nativeInputValueSetter?.call(el, suggestion);
        // Dispatch input event to trigger React state update
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.focus({ preventScroll: true });
        const len = el.value.length;
        el.setSelectionRange(len, len);
      }
    }, 50);
  }, []);
  
  // Quick feedback for feedback lock
  const openQuickFeedback = useCallback((rating: "up" | "down") => {
    const messageId = lastAssistantFeedbackMessageId;
    if (!messageId) return;
    setFeedbackTargetMessageId(messageId);
    setFeedbackRating(rating);
    setFeedbackDialogOpen(true);
  }, [lastAssistantFeedbackMessageId]);
  
  // Shared logic to recalculate scroll-to-bottom visibility
  const recalcScrollState = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const nextState = deriveViewportScrollState({
      scrollTop: container.scrollTop,
      scrollHeight: container.scrollHeight,
      clientHeight: container.clientHeight,
      wasUserAtBottom: isUserAtBottomRef.current,
      // Resize-driven updates should not silently break bottom pinning.
      preservePinnedBottom: shouldAutoFollowRef.current,
    });
    isUserAtBottomRef.current = nextState.isUserAtBottom;
    if (nextState.isUserAtBottom) {
      shouldAutoFollowRef.current = true;
    }
    setShowScrollToBottom(nextState.showScrollToBottom);
  }, []);

  const capturePrependAnchor = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) {
      prependAnchorRef.current = null;
      return;
    }

    const containerRect = container.getBoundingClientRect();
    const candidateRows = Array.from(
      container.querySelectorAll<HTMLElement>("[data-message-id]"),
    );
    const firstVisibleRow =
      candidateRows.find((row) => row.getBoundingClientRect().bottom > containerRect.top + 4) ??
      candidateRows[0] ??
      null;

    prependAnchorRef.current = {
      messageId: firstVisibleRow?.dataset.messageId ?? null,
      topOffset: firstVisibleRow
        ? firstVisibleRow.getBoundingClientRect().top - containerRect.top
        : 0,
      previousHeight: container.scrollHeight,
      previousTop: container.scrollTop,
    };
  }, []);

  const restorePrependAnchor = useCallback(() => {
    const container = scrollContainerRef.current;
    const anchor = prependAnchorRef.current;
    prependAnchorRef.current = null;
    if (!container || !anchor) return;

    if (anchor.messageId) {
      const escapedMessageId =
        typeof CSS !== "undefined" && typeof CSS.escape === "function"
          ? CSS.escape(anchor.messageId)
          : anchor.messageId.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
      const row = container.querySelector<HTMLElement>(
        `[data-message-id="${escapedMessageId}"]`,
      );
      if (row) {
        const containerRect = container.getBoundingClientRect();
        const nextTopOffset = row.getBoundingClientRect().top - containerRect.top;
        const delta = nextTopOffset - anchor.topOffset;
        if (Math.abs(delta) > SCROLL_SUBPIXEL_THRESHOLD) {
          container.scrollTop += delta;
        }
        lastObservedScrollTopRef.current = container.scrollTop;
        return;
      }
    }

    const delta = container.scrollHeight - anchor.previousHeight;
    container.scrollTop = anchor.previousTop + Math.max(0, delta);
    lastObservedScrollTopRef.current = container.scrollTop;
  }, []);

  const handleLoadOlderMessages = useCallback(async () => {
    if (chat.paging.isLoadingInitial || chat.paging.isLoadingMore || !chat.paging.hasMore) {
      return;
    }

    capturePrependAnchor();

    await chat.actions.loadOlderMessages();

    cancelAnimationFrame(prependRestoreFrameRef.current);
    prependRestoreFrameRef.current = requestAnimationFrame(() => {
      restorePrependAnchor();
      recalcScrollState();
    });
  }, [
    capturePrependAnchor,
    chat.actions,
    chat.paging.hasMore,
    chat.paging.isLoadingInitial,
    chat.paging.isLoadingMore,
    recalcScrollState,
    restorePrependAnchor,
  ]);

  const maybeLoadOlderMessages = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    if (chat.paging.isLoadingInitial || chat.paging.isLoadingMore) return;
    if (!chat.paging.hasMore || isStreaming) return;
    if (container.scrollTop > SCROLL_NEAR_TOP_PX) return;
    void handleLoadOlderMessages();
  }, [
    chat.paging.hasMore,
    chat.paging.isLoadingInitial,
    chat.paging.isLoadingMore,
    handleLoadOlderMessages,
    isStreaming,
  ]);

  // Handle scroll position for scroll-to-bottom button
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    lastObservedScrollTopRef.current = container.scrollTop;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const maxScrollTop = Math.max(0, scrollHeight - clientHeight);
      const previousScrollTop = lastObservedScrollTopRef.current;
      const userScrolledUp = scrollTop < previousScrollTop - 1;
      if (userScrolledUp) {
        shouldAutoFollowRef.current = false;
      }

      // Guard against boundary overshoot jitter at the bottom/top.
      if (scrollTop < 0) {
        container.scrollTop = 0;
        lastObservedScrollTopRef.current = container.scrollTop;
        return;
      }
      if (scrollTop > maxScrollTop) {
        container.scrollTop = maxScrollTop;
        lastObservedScrollTopRef.current = container.scrollTop;
        return;
      }

      const preservePinnedBottom = shouldPreservePinnedBottomOnScroll({
        autoFollowEnabled: shouldAutoFollowRef.current,
        previousScrollTop,
        currentScrollTop: scrollTop,
      });
      const nextState = deriveViewportScrollState({
        scrollTop: container.scrollTop,
        scrollHeight: container.scrollHeight,
        clientHeight: container.clientHeight,
        wasUserAtBottom: isUserAtBottomRef.current,
        preservePinnedBottom,
      });
      isUserAtBottomRef.current = nextState.isUserAtBottom;
      if (nextState.isUserAtBottom) {
        shouldAutoFollowRef.current = true;
      }
      setShowScrollToBottom(nextState.showScrollToBottom);
      lastObservedScrollTopRef.current = container.scrollTop;
      maybeLoadOlderMessages();
    };

    const disableAutoFollowFromUserInput = () => {
      if (!shouldAutoFollowRef.current) return;
      shouldAutoFollowRef.current = false;
      requestAnimationFrame(() => {
        recalcScrollState();
      });
    };

    const handleWheel = (event: WheelEvent) => {
      // Upward wheel intent means "let me inspect older messages".
      if (event.deltaY < 0) {
        disableAutoFollowFromUserInput();
      }
    };

    const handleTouchStart = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY;
      touchStartYRef.current = typeof y === "number" ? y : null;
    };

    const handleTouchMove = (event: TouchEvent) => {
      const prevY = touchStartYRef.current;
      const nextY = event.touches[0]?.clientY;
      if (typeof prevY === "number" && typeof nextY === "number") {
        // Finger moving down means content scrolling up.
        if (nextY > prevY + 2) {
          disableAutoFollowFromUserInput();
        }
        touchStartYRef.current = nextY;
      }
    };

    const handleTouchEnd = () => {
      touchStartYRef.current = null;
    };

    container.addEventListener("scroll", handleScroll);
    container.addEventListener("wheel", handleWheel, { passive: true });
    container.addEventListener("touchstart", handleTouchStart, { passive: true });
    container.addEventListener("touchmove", handleTouchMove, { passive: true });
    container.addEventListener("touchend", handleTouchEnd, { passive: true });
    container.addEventListener("touchcancel", handleTouchEnd, { passive: true });

    return () => {
      container.removeEventListener("scroll", handleScroll);
      container.removeEventListener("wheel", handleWheel);
      container.removeEventListener("touchstart", handleTouchStart);
      container.removeEventListener("touchmove", handleTouchMove);
      container.removeEventListener("touchend", handleTouchEnd);
      container.removeEventListener("touchcancel", handleTouchEnd);
    };
  }, [maybeLoadOlderMessages, recalcScrollState]);

  // Recalculate scroll state when content height changes (e.g. worklog collapse/expand).
  // Scroll events alone miss CSS-animated height transitions.
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const ro = new ResizeObserver(() => {
      recalcScrollState();
    });

    // Observe the first child (the content wrapper) so we detect inner height changes
    const content = container.firstElementChild;
    if (content) {
      ro.observe(content);
    }
    // Also observe the container itself for viewport size changes
    ro.observe(container);

    return () => ro.disconnect();
  }, [recalcScrollState]);
  
  // Scroll to bottom function
  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior: "smooth",
      });
      isUserAtBottomRef.current = true;
      shouldAutoFollowRef.current = true;
      lastObservedScrollTopRef.current = scrollContainerRef.current.scrollTop;
    }
  }, []);

  const handlePinnedBottom = useCallback(() => {
    isUserAtBottomRef.current = true;
    setShowScrollToBottom(false);
  }, []);

  useEffect(() => {
    if (!isStreaming || !shouldAutoFollowRef.current || !scrollContainerRef.current) {
      return;
    }

    requestAnimationFrame(() => {
      if (!scrollContainerRef.current || !shouldAutoFollowRef.current) {
        return;
      }
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      lastObservedScrollTopRef.current = scrollContainerRef.current.scrollTop;
      handlePinnedBottom();
    });
  }, [visibleTimeline, handlePinnedBottom, isStreaming, liveStream.content, liveStream.phase]);

  // Scroll to bottom instantly on initial load (no animation)
  const hasScrolledOnLoadRef = useRef(false);
  const initialScrollConversationIdRef = useRef<string | null>(null);
  useEffect(() => {
    const decision = resolveInitialScrollDecision({
      conversationId,
      trackedConversationId: initialScrollConversationIdRef.current,
      hasScrolledOnLoad: hasScrolledOnLoadRef.current,
      isLoadingInitial: chat.paging.isLoadingInitial,
      timelineLength: visibleTimeline.length,
    });
    initialScrollConversationIdRef.current = decision.nextConversationId;
    hasScrolledOnLoadRef.current = decision.nextHasScrolledOnLoad;
    if (!decision.shouldScrollNow) return;
    // Use requestAnimationFrame to ensure messages are rendered.
    requestAnimationFrame(() => {
      if (!scrollContainerRef.current) return;
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      isUserAtBottomRef.current = true;
      shouldAutoFollowRef.current = true;
      setShowScrollToBottom(false);
      lastObservedScrollTopRef.current = scrollContainerRef.current.scrollTop;
    });
  }, [conversationId, chat.paging.isLoadingInitial, visibleTimeline.length]);

  useEffect(() => {
    if (chat.paging.isLoadingInitial || chat.paging.isLoadingMore) return;
    if (!chat.paging.hasMore || isStreaming) return;
    const container = scrollContainerRef.current;
    if (!container) return;
    if (container.scrollHeight <= container.clientHeight + SCROLL_NEAR_TOP_PX || container.scrollTop <= SCROLL_NEAR_TOP_PX) {
      void handleLoadOlderMessages();
    }
  }, [
    chat.paging.hasMore,
    chat.paging.isLoadingInitial,
    chat.paging.isLoadingMore,
    visibleTimeline.length,
    handleLoadOlderMessages,
    isStreaming,
  ]);

  useEffect(() => {
    return () => {
      cancelAnimationFrame(prependRestoreFrameRef.current);
    };
  }, []);

  // When the virtual keyboard opens/closes, keep the scroll position pinned to
  // the bottom if the user was already there, so the latest messages stay visible.
  const viewportRafRef = useRef(0);
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    const handleViewportResize = () => {
      if (!shouldAutoFollowRef.current || !scrollContainerRef.current) return;
      // Cancel any previously scheduled frame to avoid redundant scroll writes
      // during rapid viewport resize events (e.g. keyboard animation).
      cancelAnimationFrame(viewportRafRef.current);
      // Schedule after layout so the parent has already adjusted padding.
      viewportRafRef.current = requestAnimationFrame(() => {
        if (scrollContainerRef.current && shouldAutoFollowRef.current) {
          scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
          lastObservedScrollTopRef.current = scrollContainerRef.current.scrollTop;
          isUserAtBottomRef.current = true;
        }
      });
    };

    vv.addEventListener("resize", handleViewportResize);
    return () => {
      vv.removeEventListener("resize", handleViewportResize);
      cancelAnimationFrame(viewportRafRef.current);
    };
  }, []);

  const showFollowUpSuggestions = canEdit && !isStreaming && !feedbackLock && !isPausedForInput;
  const queuedComposerItems = useMemo(() => {
    if (!queuedTurns.length) return [];
    return queuedTurns
      .map((queuedTurn) => {
        const matchingMessage = chat.timeline.find((message) => message.id === queuedTurn.userMessageId);
        const text = queuedTurn.text?.trim() || (matchingMessage ? resolveMessageText(matchingMessage, true).trim() : "");
        return {
          queuePosition: queuedTurn.queuePosition,
          runId: queuedTurn.runId,
          text: text || "Queued follow-up",
        };
      })
      .sort((left, right) => left.queuePosition - right.queuePosition);
  }, [chat.timeline, queuedTurns]);

  // Whether the shelf overlay above the composer is actually rendered
  // (drives extra bottom-padding on the scroll area so the shelf doesn't cover messages)
  const hasSuggestionsShelf = showFollowUpSuggestions && (
    !!lastAssistantMessageId || isGeneratingSuggestions || (suggestedQuestions && suggestedQuestions.length > 0)
  );
  const hasQueuedShelf = queuedComposerItems.length > 0;
  const hasActiveShelf = hasQueuedShelf || hasSuggestionsShelf || (showMemoryWarning && viewerIsOwner);

  const composerTopSlotNode = useMemo(() => {
    const hasMemoryRow = showMemoryWarning && viewerIsOwner;
    const memoryWarningRow = hasMemoryRow ? (
      <div className="flex items-center gap-2 px-3.5 py-2 type-size-12 bg-amber-50/60 dark:bg-amber-950/15">
        <Warning className="h-3.5 w-3.5 text-amber-500 dark:text-amber-400 shrink-0" />
        <span className="flex-1 font-medium text-amber-900 dark:text-amber-100">
          Context at {memoryPercent}%{" "}
          <span className="font-normal opacity-75">— this chat will auto-compact when needed</span>
        </span>
      </div>
    ) : null;
    const queuedMessagesNode = hasQueuedShelf ? (
      <QueuedMessagesShelf items={queuedComposerItems} />
    ) : null;

    const suggestionsNode = showFollowUpSuggestions ? (
      <FollowUpSuggestions
        suggestions={suggestedQuestions}
        isGenerating={isGeneratingSuggestions}
        isExpanded={isSuggestionsExpanded}
        onToggleExpanded={() => setIsSuggestionsExpanded((v) => !v)}
        onGenerate={handleGenerateSuggestions}
        onSuggestionClick={handleSuggestionClick}
        hasAssistantMessage={!!lastAssistantMessageId}
        bare
      />
    ) : null;

    if (!queuedMessagesNode && !memoryWarningRow && !suggestionsNode) return null;

    return (
      <div className="w-full divide-y divide-border/10">
        {queuedMessagesNode}
        {memoryWarningRow}
        {suggestionsNode}
      </div>
    );
  }, [
    hasQueuedShelf,
    queuedComposerItems,
    showMemoryWarning,
    viewerIsOwner,
    memoryPercent,
    showFollowUpSuggestions,
    suggestedQuestions,
    isGeneratingSuggestions,
    isSuggestionsExpanded,
    handleGenerateSuggestions,
    handleSuggestionClick,
    lastAssistantMessageId,
  ]);

  // Push composer shelves into topContent.
  useEffect(() => {
    if (!onComposerTopSlot) return;
    onComposerTopSlot(composerTopSlotNode);
  }, [
    onComposerTopSlot,
    composerTopSlotNode,
  ]);

  // Cleanup: clear the top slot on unmount
  useEffect(() => {
    if (!onComposerTopSlot) return;
    return () => onComposerTopSlot(null);
  }, [onComposerTopSlot]);

  // If the user is already pinned to bottom, keep them pinned while
  // bottom shelves mount/expand/collapse so the latest message
  // doesn't appear covered by the bottom UI.
  useEffect(() => {
    if (!hasActiveShelf) return;
    if (!isUserAtBottomRef.current || !scrollContainerRef.current) return;
    requestAnimationFrame(() => {
      if (scrollContainerRef.current && isUserAtBottomRef.current) {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      }
    });
  }, [
    hasActiveShelf,
    suggestedQuestions,
    isSuggestionsExpanded,
    isGeneratingSuggestions,
  ]);

  // Drag-and-drop handlers
  const handleDragEnter = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.types && e.dataTransfer.types.includes("Files")) {
      dragCancelledRef.current = false;
      dragCounterRef.current += 1;
      if (dragCounterRef.current === 1) {
        setIsDragging(true);
      }
    }
  }, [setIsDragging]);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDragging(false);
    }
  }, [setIsDragging]);

  const handleDrop = useCallback(async (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    const wasCancelled = dragCancelledRef.current;
    dragCancelledRef.current = false;
    setIsDragging(false);
    if (wasCancelled) return;
    const files = e.dataTransfer.files;
    if (files && files.length > 0 && onFilesDropped) {
      await onFilesDropped(files);
    }
  }, [setIsDragging, onFilesDropped]);

  // Clean up drag state on unmount
  useEffect(() => {
    const handleDragEnd = (e: globalThis.DragEvent) => {
      if (e.dataTransfer && e.dataTransfer.dropEffect === "none") {
        dragCounterRef.current = 0;
        dragCancelledRef.current = true;
        setIsDragging(false);
      }
    };
    window.addEventListener("dragend", handleDragEnd);
    return () => window.removeEventListener("dragend", handleDragEnd);
  }, [setIsDragging]);

  useEffect(() => {
    return () => {
      dragCounterRef.current = 0;
      dragCancelledRef.current = false;
      setIsDragging(false);
    };
  }, [setIsDragging]);

  return (
    <div
      ref={rootRef}
      className={cn("flex flex-col h-full relative", className)}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* File drop overlay */}
      <FileDropOverlay isVisible={isDragging} />

      {/* Messages area */}
      <div
        ref={scrollContainerRef}
        className={cn(
          "relative flex-1 overflow-y-auto overscroll-y-none px-3 md:px-4 transition-[padding-bottom] duration-200",
          hasActiveShelf
            ? (showMemoryWarning && viewerIsOwner) ? "pb-18" : "pb-8"
            : "pb-2",
        )}
        style={{ overscrollBehaviorY: "none", scrollbarGutter: "stable both-edges", overflowAnchor: "none" }}
      >
        <div className="mx-auto max-w-[var(--thread-max-width,46rem)]">
          {/* Loading state */}
          {chat.paging.isLoadingInitial && visibleTimeline.length === 0 && (
            <div className="flex items-center justify-center py-12">
              <SpinnerGap className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {/* Error state */}
          {chatError && !isStreaming && (
            <div className="mx-auto max-w-2xl px-4 py-8">
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 type-size-14 text-red-900 dark:border-red-800 dark:bg-red-950/30 dark:text-red-200">
                <div className="flex items-start gap-2">
                  <Warning className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <p className="font-medium">Something went wrong</p>
                    <p className="type-size-12 mt-1 opacity-80">{chatError.message}</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Welcome message when empty and not streaming */}
          {!chat.paging.isLoadingInitial && visibleTimeline.length === 0 && !chatError && !isStreaming && (
            <WelcomeMessage />
          )}

          {/* Message list */}
          {chat.paging.hasMore && (
            <div className="flex justify-center py-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleLoadOlderMessages}
                disabled={chat.paging.isLoadingMore || isStreaming}
              >
                {chat.paging.isLoadingMore ? (
                  <>
                    <SpinnerGap className="mr-2 h-3.5 w-3.5 animate-spin" />
                    Loading older messages
                  </>
                ) : (
                  "Load older messages"
                )}
              </Button>
            </div>
          )}

          <MessageList
            messages={visibleTimeline}
            conversationId={conversationId}
            viewerIsOwner={viewerIsOwner}
            getScrollElement={() => scrollContainerRef.current}
          />

          {/* Scroll to bottom button stays within the message viewport */}
          <AnimatePresence>
            {showScrollToBottom && (
              <motion.div
                initial={{ opacity: 0, y: 8, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.95 }}
                transition={{ duration: 0.16 }}
                className="pointer-events-none sticky bottom-2.5 z-20 mx-auto flex h-0 max-w-[var(--thread-max-width,46rem)] justify-center px-1"
              >
                <motion.button
                  whileHover={{ scale: 1.04 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={scrollToBottom}
                  className="pointer-events-auto inline-flex -translate-y-full items-center justify-center rounded-full border border-primary/30 bg-primary p-2.5 text-primary-foreground shadow-lg shadow-primary/20 transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2"
                  aria-label="Scroll to bottom"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </motion.button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Bottom bar: feedback/canEdit notices (input lives in parent) */}
      <div className="shrink-0 px-3 relative">
        <div className="mx-auto max-w-[var(--thread-max-width,46rem)]">
          {!canEdit ? (
            <div className="text-center type-size-12 text-muted-foreground py-2">
              Only the owner can continue this chat. Branch it to make your own copy.
            </div>
          ) : feedbackLock ? (
            <FeedbackLockUI
              hasAssistantMessage={!!lastAssistantFeedbackMessageId}
              onThumbsUp={() => openQuickFeedback("up")}
              onThumbsDown={() => openQuickFeedback("down")}
            />
          ) : null}
        </div>
      </div>
      
      {/* Feedback dialog */}
      {feedbackTargetMessageId && feedbackRating && (
        <MessageFeedbackDialog
          open={feedbackDialogOpen}
          onClose={() => setFeedbackDialogOpen(false)}
          conversationId={conversationId}
          messageId={feedbackTargetMessageId}
          rating={feedbackRating}
          onSuccess={() => {
            setFeedbackDialogOpen(false);
            setFeedbackTargetMessageId(null);
            setFeedbackRating(null);
            // Unlock feedback
            setFeedbackLock(false);
          }}
        />
      )}
    </div>
  );
};

// ============================================================================
// FeedbackLockUI Component
// ============================================================================

type FeedbackLockUIProps = {
  hasAssistantMessage: boolean;
  onThumbsUp: () => void;
  onThumbsDown: () => void;
};

const FeedbackLockUI: FC<FeedbackLockUIProps> = ({
  hasAssistantMessage,
  onThumbsUp,
  onThumbsDown,
}) => {
  const commonBtn = "inline-flex items-center gap-1.5 h-8 px-3 type-size-12 font-medium cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors";
  
  return (
    <div className="flex w-full flex-col gap-2 rounded-xl border border-primary/10 bg-primary/5 px-3 sm:px-5 py-3 sm:py-3.5 type-size-14 text-foreground">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 type-size-16 font-medium text-foreground">
        <div role="group" aria-label="Quick feedback" className="inline-flex items-center rounded-full border border-primary/20 bg-background/70 overflow-hidden">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn(commonBtn, "border-r border-border/40 hover:bg-emerald-500/10 rounded-none")}
            aria-label="Rate last response as good"
            title={hasAssistantMessage ? "Good" : "No assistant response to rate yet"}
            onClick={onThumbsUp}
            disabled={!hasAssistantMessage}
          >
            <ThumbsUp className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn(commonBtn, "hover:bg-rose-500/10 rounded-none")}
            aria-label="Rate last response as needs improvement"
            title={hasAssistantMessage ? "Needs improvement" : "No assistant response to rate yet"}
            onClick={onThumbsDown}
            disabled={!hasAssistantMessage}
          >
            <ThumbsDown className="h-4 w-4 text-rose-600 dark:text-rose-400" />
          </Button>
        </div>
        <span className="text-muted-foreground type-size-14">
          Please rate the last response to continue chatting
        </span>
      </div>
    </div>
  );
};

// ============================================================================
// FollowUpSuggestions Component
// ============================================================================

type FollowUpSuggestionsProps = {
  suggestions: string[] | null;
  isGenerating: boolean;
  isExpanded: boolean;
  onToggleExpanded: () => void;
  onGenerate: () => void;
  onSuggestionClick: (suggestion: string) => void;
  hasAssistantMessage: boolean;
  /** When true, renders without its own border/bg (parent card provides chrome) */
  bare?: boolean;
};

const FollowUpSuggestions: FC<FollowUpSuggestionsProps> = ({
  suggestions,
  isGenerating,
  isExpanded,
  onToggleExpanded,
  onGenerate,
  onSuggestionClick,
  hasAssistantMessage,
  bare = false,
}) => {
  // Show suggestions panel if we have suggestions
  if (suggestions && suggestions.length > 0) {
    return (
      <CollapsibleInlineList
        icon={<Lightbulb className="h-3.5 w-3.5 text-primary" />}
        label="Suggested follow-ups"
        expanded={isExpanded}
        onToggle={onToggleExpanded}
        bare={bare}
        className={bare ? undefined : "mb-1"}
      >
        {suggestions.map((suggestion, index) => (
          <Button
            key={`${suggestion}-${index}`}
            type="button"
            variant="ghost"
            onClick={() => onSuggestionClick(suggestion)}
            className="group flex min-h-[2rem] w-full items-center justify-start gap-2 px-3.5 py-1.5 text-left transition-colors hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 h-auto rounded-none active:!scale-100"
          >
            <span className="flex-1 type-size-12 leading-relaxed truncate font-medium text-foreground/85 group-hover:text-foreground">
              {suggestion}
            </span>
          </Button>
        ))}
      </CollapsibleInlineList>
    );
  }

  // Show loading state
  if (isGenerating) {
    return (
      <div className={cn("w-full", !bare && "mb-1")}>
        <div className={cn(
          "flex w-full items-center gap-2 px-3.5 py-2 type-size-12 font-medium text-foreground/70",
          !bare && "rounded-lg border border-border/60 bg-background/50 backdrop-blur-sm"
        )}>
          <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
          <span>Generating suggestions</span>
        </div>
      </div>
    );
  }

  // Show generate button if there's an assistant message
  if (hasAssistantMessage) {
    return (
      <div className={cn("w-full", !bare && "mb-1")}>
        <Button
          type="button"
          variant="ghost"
          onClick={onGenerate}
          className={cn(
            "flex w-full items-center justify-start gap-2 px-3.5 py-2 type-size-12 font-medium text-foreground/70 hover:bg-muted/20 transition-colors h-auto active:!scale-100",
            bare
              ? "rounded-none"
              : "rounded-lg border border-border/60 bg-background/50 backdrop-blur-sm"
          )}
        >
          <Lightbulb className="h-3.5 w-3.5 text-[#DA4F27]" />
          <span className="type-size-12 font-medium">Get suggested follow-ups</span>
        </Button>
      </div>
    );
  }

  return null;
};

type QueuedComposerItem = {
  queuePosition: number;
  runId: string;
  text: string;
};

const QueuedMessagesShelf: FC<{ items: QueuedComposerItem[] }> = ({ items }) => {
  const [expanded, setExpanded] = useState(true);

  if (items.length === 0) return null;

  return (
    <CollapsibleInlineList
      icon={<SpinnerGap className="h-3.5 w-3.5 animate-spin text-primary" />}
      label={items.length === 1 ? "Queued follow-up" : "Queued follow-ups"}
      headerExtra={(
        <span className="rounded-full bg-primary/10 px-2 py-0.5 type-size-10 font-semibold uppercase tracking-wide text-primary">
          {items.length}
        </span>
      )}
      expanded={expanded}
      onToggle={() => setExpanded((current) => !current)}
      bare
    >
        {items.map((item) => (
          <div
            key={item.runId}
            className="flex min-h-[2rem] items-center gap-2 px-3.5 py-1.5"
          >
            <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 type-size-10 font-semibold uppercase tracking-wide text-primary">
              {item.queuePosition === 1 ? "Next" : `#${item.queuePosition}`}
            </span>
            <span className="min-w-0 flex-1 truncate type-size-12 leading-relaxed font-medium text-foreground/85">
              {item.text}
            </span>
          </div>
        ))}
    </CollapsibleInlineList>
  );
};

// ============================================================================
// WelcomeMessage Component
// ============================================================================

const WelcomeMessage: FC = () => {
  const { user, isAuthenticated, isBackendAuthenticated, isLoading } = useAuth();
  
  const firstName = user?.name ? user.name.split(" ")[0] : "";
  const canShowGreeting = !isLoading && isAuthenticated && isBackendAuthenticated && !!firstName;

  return (
    <div className="flex w-full max-w-[var(--thread-max-width)] flex-grow flex-col items-center justify-center py-12 text-center">
      <h3
        className={cn(
          "type-size-32 font-normal mb-6 text-muted-foreground tracking-tight transition-opacity duration-700 min-h-[2.25rem]",
          canShowGreeting ? "opacity-100" : "opacity-0",
        )}
        aria-hidden={!canShowGreeting}
      >
        Hey{canShowGreeting ? ", " : ""}
        <span
          className={cn("inline-block", canShowGreeting && "animate-slide-down-fade")}
          style={canShowGreeting ? { animationDuration: "700ms" } : undefined}
        >
          {canShowGreeting ? firstName : ""}
        </span>
      </h3>
    </div>
  );
};

export default ChatView;
