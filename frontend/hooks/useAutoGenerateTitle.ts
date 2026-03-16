import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchWithAuth } from "@/lib/api/auth";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";
import { isDefaultConversationTitle } from "@/lib/conversation-titles";
import { patchConversationTitleInCaches } from "@/lib/chat/conversation-list";

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;

type TitleResponsePayload = {
  title?: string;
};

// Track processed conversations for the lifetime of this browser tab.
const processedConversationIds = new Set<string>();

/**
 * Generates a title once per conversation per tab and relies on the shared
 * user-events channel for broader sidebar freshness.
 */
export const useAutoGenerateTitle = (
  conversationId?: string,
  conversationTitle?: string | null,
) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pathname = useLocation().pathname;

  // Track external title updates (manual rename or other clients) so we don't rerun
  useEffect(() => {
    if (!conversationId) return;

    const handleTitleUpdated = (event: Event) => {
      const detail = (event as CustomEvent).detail as
        | { conversationId?: string; title?: string | null }
        | undefined;
      if (!detail || detail.conversationId !== conversationId) return;

      processedConversationIds.add(conversationId);
    };

    window.addEventListener(
      "backend:titleUpdated",
      handleTitleUpdated as EventListener,
    );
    return () => {
      window.removeEventListener(
        "backend:titleUpdated",
        handleTitleUpdated as EventListener,
      );
    };
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId) return;
    const currentTitle = (conversationTitle ?? "").trim();
    if (currentTitle && !isDefaultConversationTitle(currentTitle)) {
      processedConversationIds.add(conversationId);
      return;
    }
    if (processedConversationIds.has(conversationId)) return;

    const controller = new AbortController();
    let finished = false;

    const finish = (title: string | null) => {
      if (finished) return;
      finished = true;

      processedConversationIds.add(conversationId);
      patchConversationTitleInCaches(queryClient, {
        conversationId,
        title,
      });
      try {
        window.dispatchEvent(
          new CustomEvent("backend:titleUpdated", {
            detail: { conversationId, title },
          }),
        );
      } catch {}
      if (pathname === "/") {
        try {
          navigate(`/chat/${conversationId}`, { replace: true });
        } catch {}
      }
    };

    const run = async () => {
      try {
        const backendBase = getBackendBaseUrl();
        const response = await fetchWithAuth(
          `${backendBase}/conversations/${conversationId}/title`,
          {
            method: "POST",
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          throw new Error(`Title generation failed: ${response.status}`);
        }

        const payload = await response.json().catch(() => null) as TitleResponsePayload | null;
        const title =
          payload && isNonEmptyString(payload.title)
            ? payload.title.trim()
            : null;
        finish(title);
      } catch (_error) {
        if (controller.signal.aborted) return;
        // Title generation failed; user may need to rename manually
        finish(null);
      }
    };

    void run();

    return () => {
      controller.abort();
    };
  }, [conversationId, conversationTitle, pathname, navigate, queryClient]);
};
