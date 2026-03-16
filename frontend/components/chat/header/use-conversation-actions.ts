import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { createShareLink } from "@/lib/api/share";
import {
  branchConversation,
  conversationResponseToSummary,
  getLatestConversationMessageId,
} from "@/lib/api/auth";
import { getMessagesFromCache } from "@/lib/cache/messages-cache";
import { upsertConversationSummary } from "@/lib/chat/conversation-list";
import { tryWebShare, tryClipboardWrite } from "@/lib/share-helpers";
import { type Project } from "@/lib/api/projects-core";
import { hasMeaningfulContextUsage } from "@/lib/chat/context-usage";
import type { Toast } from "@/components/ui/toast";
import type { ConversationSummary as ConvSummary, ConversationContextUsage } from "@/lib/api/auth";

type UseConversationActionsParams = {
  conversationId: string | undefined;
  projectId: string | undefined;
  project: Project | null;
  currentConversationProjectId: string | null;
  conversations: ConvSummary[];
  viewerIsOwner: boolean;
  refreshConversations: (() => void) | undefined;
  updateConversations: (updater: (current: ConvSummary[]) => ConvSummary[]) => void;
  addToast: (toast: Omit<Toast, "id">) => void;
  isAdmin: boolean;
};

export type ConversationActionsState = {
  isSharing: boolean;
  isBranching: boolean;
  isProjectDialogOpen: boolean;
  setIsProjectDialogOpen: (open: boolean) => void;
  shareFallbackOpen: boolean;
  setShareFallbackOpen: (open: boolean) => void;
  shareFallbackUrl: string | null;
  showInstructions: boolean;
  setShowInstructions: (show: boolean) => void;
  parentConversationId: string | undefined;
  hasParentConversation: boolean;
  conversationUsage: ConversationContextUsage | null;
  handleShare: () => Promise<void>;
  handleBranchFromLast: () => Promise<void>;
  handleRequestEditProject: () => void;
  goToOriginal: () => void;
};

export function useConversationActions({
  conversationId,
  projectId,
  project,
  currentConversationProjectId,
  conversations,
  viewerIsOwner,
  refreshConversations,
  updateConversations,
  addToast,
  isAdmin,
}: UseConversationActionsParams): ConversationActionsState {
  const navigate = useNavigate();

  const toStableUsage = useCallback((usage: ConversationContextUsage | null | undefined): ConversationContextUsage | null => {
    if (!usage) return null;
    if (!hasMeaningfulContextUsage(usage)) return null;
    return usage;
  }, []);

  const [isSharing, setIsSharing] = useState(false);
  const [isBranching, setIsBranching] = useState(false);
  const [isProjectDialogOpen, setIsProjectDialogOpen] = useState(false);
  const [shareFallbackOpen, setShareFallbackOpen] = useState(false);
  const [shareFallbackUrl, setShareFallbackUrl] = useState<string | null>(null);
  const [showInstructions, setShowInstructions] = useState(false);

  const currentConversation = useMemo(() => {
    if (!conversationId) return undefined;
    return conversations.find((c) => c.id === conversationId);
  }, [conversationId, conversations]);

  const parentConversationId = useMemo(
    () => (currentConversation?.parent_conversation_id ?? undefined) || undefined,
    [currentConversation],
  );

  const parentConversation = useMemo(() => {
    if (!parentConversationId) return undefined;
    return conversations.find((c) => c.id === parentConversationId);
  }, [conversations, parentConversationId]);
  const hasParentConversation = Boolean(parentConversationId && parentConversation);

  // Conversation usage — tracks live token usage in the header badge
  const usageByConversationRef = useRef<Map<string, ConversationContextUsage>>(new Map());
  const [conversationUsage, setConversationUsage] = useState<ConversationContextUsage | null>(() => {
    const stableUsage = toStableUsage(currentConversation?.context_usage ?? null);
    if (conversationId && stableUsage) {
      usageByConversationRef.current.set(conversationId, stableUsage);
    }
    return stableUsage;
  });

  useEffect(() => {
    if (!conversationId) {
      setConversationUsage(null);
      return;
    }

    const stableUsage = toStableUsage(currentConversation?.context_usage ?? null);
    if (stableUsage) {
      usageByConversationRef.current.set(conversationId, stableUsage);
      setConversationUsage(stableUsage);
      return;
    }

    setConversationUsage(usageByConversationRef.current.get(conversationId) ?? null);
  }, [conversationId, currentConversation?.context_usage, toStableUsage]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ conversationId: string; usage: ConversationContextUsage | null }>).detail;
      if (!detail || detail.conversationId !== conversationId) return;
      const stableUsage = toStableUsage(detail.usage ?? null);
      if (stableUsage) {
        usageByConversationRef.current.set(detail.conversationId, stableUsage);
      }
      const resolvedUsage =
        stableUsage ?? usageByConversationRef.current.get(detail.conversationId) ?? null;
      setConversationUsage(resolvedUsage);
      updateConversations((current) =>
        current.map((item) =>
          item.id === detail.conversationId
            ? { ...item, context_usage: resolvedUsage ?? item.context_usage ?? null }
            : item,
        ),
      );
    };
    window.addEventListener("frontend:conversationUsageUpdated", handler as EventListener);
    return () => window.removeEventListener("frontend:conversationUsageUpdated", handler as EventListener);
  }, [conversationId, toStableUsage, updateConversations]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ conversationId: string; requiresFeedback: boolean }>).detail;
      if (!detail) return;
      if (isAdmin) return;
      updateConversations((current) =>
        current.map((item) =>
          item.id === detail.conversationId ? { ...item, requires_feedback: detail.requiresFeedback } : item,
        ),
      );
    };
    window.addEventListener("frontend:conversationFeedbackStatus", handler as EventListener);
    return () => window.removeEventListener("frontend:conversationFeedbackStatus", handler as EventListener);
  }, [updateConversations, isAdmin]);

  const goToOriginal = useCallback(() => {
    if (!parentConversationId || !parentConversation) return;
    const dest = parentConversation?.project_id
      ? `/projects/${parentConversation.project_id}/chat/${parentConversationId}`
      : `/chat/${parentConversationId}`;
    try {
      navigate(dest);
    } catch {
      window.location.assign(dest);
    }
  }, [parentConversationId, parentConversation, navigate]);

  const handleShare = useCallback(async () => {
    if (!conversationId || isSharing) return;
    if (!viewerIsOwner) {
      addToast({
        type: "error",
        title: "Only owners can share",
        description: "Branch this conversation first, then you can share your copy.",
      });
      return;
    }
    setIsSharing(true);
    try {
      const response = await createShareLink(conversationId);
      const url = response.share_url;
      const shared = await tryWebShare({
        url,
        title: "assistant - Shared conversation",
        text: "Use this link to import the conversation (valid for 7 days).",
      });
      if (shared) {
        addToast({ type: "success", title: "Share sheet opened" });
        return;
      }
      const copied = await tryClipboardWrite(url);
      if (copied) {
        addToast({
          type: "success",
          title: "Share link copied!",
          description: "Anyone with this link can import this conversation for 7 days.",
        });
        return;
      }
      setShareFallbackUrl(url);
      setShareFallbackOpen(true);
      addToast({ type: "info", title: "Link ready — tap Copy" });
    } catch (error) {
      addToast({
        type: "error",
        title: "Failed to create share link",
        description: error instanceof Error ? error.message : "Please try again",
      });
    } finally {
      setIsSharing(false);
    }
  }, [conversationId, isSharing, viewerIsOwner, addToast]);

  const handleBranchFromLast = useCallback(async () => {
    if (!conversationId || isBranching) return;
    const cached = getMessagesFromCache(conversationId);
    const lastMessage = cached?.filter((m) => m.id).pop();
    let targetMessageId = lastMessage?.id ?? null;

    if (!targetMessageId) {
      try {
        targetMessageId = await getLatestConversationMessageId(conversationId);
      } catch (error) {
        addToast({
          type: "error",
          title: "Failed to load latest message",
          description: error instanceof Error ? error.message : "Please try again.",
        });
        return;
      }
    }

    if (!targetMessageId) {
      addToast({ type: "error", title: "No messages to branch from" });
      return;
    }
    setIsBranching(true);
    try {
      const response = await branchConversation(conversationId, targetMessageId);
      const summary = conversationResponseToSummary(response);
      try {
        window.dispatchEvent(
          new CustomEvent("frontend:conversationCreated", {
            detail: { conversation: response },
          }),
        );
      } catch { }
      updateConversations((current) => upsertConversationSummary(current, summary).next);
      refreshConversations?.();
      const href = summary.project_id
        ? `/projects/${summary.project_id}/chat/${summary.id}`
        : `/chat/${summary.id}`;
      navigate(href);
      addToast({ type: "success", title: "Conversation branched" });
    } catch (error) {
      addToast({
        type: "error",
        title: "Failed to branch",
        description: error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      setIsBranching(false);
    }
  }, [conversationId, isBranching, addToast, navigate, refreshConversations, updateConversations]);

  const handleRequestEditProject = useCallback(() => {
    const targetId = projectId ?? currentConversationProjectId ?? project?.id ?? null;
    if (!targetId) return;
    try {
      window.dispatchEvent(new CustomEvent("frontend:requestProjectEdit", { detail: { projectId: targetId } }));
    } catch {
      // Swallow; opening the dialog isn't critical
    }
  }, [projectId, currentConversationProjectId, project?.id]);

  return {
    isSharing,
    isBranching,
    isProjectDialogOpen,
    setIsProjectDialogOpen,
    shareFallbackOpen,
    setShareFallbackOpen,
    shareFallbackUrl,
    showInstructions,
    setShowInstructions,
    parentConversationId,
    hasParentConversation,
    conversationUsage,
    handleShare,
    handleBranchFromLast,
    handleRequestEditProject,
    goToOriginal,
  };
}
