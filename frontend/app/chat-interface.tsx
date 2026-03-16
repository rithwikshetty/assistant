
import { ChatView, type ComposerBridge } from "@/components/chat/chat-view";
import { ChatInput } from "@/components/chat/chat-input";
import { UserInputOverlay } from "@/components/chat/user-input-overlay";
import { UpcomingTasks } from "@/components/chat/upcoming-tasks";
import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { StartNewChat, ProjectRecentActivity } from "@/components/chat/start-new-chat";
import { useConversations } from "@/hooks/use-conversations";
import { useProjects } from "@/hooks/use-projects";
import { getProject, type Project } from "@/lib/api/projects-core";
import {
  conversationResponseToSummary,
  type ConversationResponsePayload,
} from "@/lib/api/auth";
import { upsertConversationSummary } from "@/lib/chat/conversation-list";
import { ProjectMembersProvider } from "@/contexts/project-members-context";
import { FileDropProvider } from "@/contexts/file-drop-context";
import { InsightSidebarProvider } from "@/components/chat/insights/insight-sidebar-context";
import { ConversationInsightsLayout } from "@/components/chat/conversation-insights-layout";
import { ChatHeader } from "@/components/chat/header/chat-header";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import type { ReactNode } from "react";
import {
  DEFAULT_CONVERSATION_TITLE,
  isDefaultConversationTitle,
} from "@/lib/conversation-titles";
import { useVirtualKeyboard } from "@/hooks/use-virtual-keyboard";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  useConversationInputGate,
  useConversationStreamMeta,
} from "@/contexts/active-streams-context";

type ChatInterfaceProps = {
  conversationId?: string;
  projectId?: string;
};

export const ChatInterface = ({ conversationId, projectId }: ChatInterfaceProps) => {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const {
    conversations,
    isLoading: conversationsLoading,
    error: conversationsError,
    refreshConversations,
    updateConversations,
  } = useConversations();
  const { updateProjects: updateProjectCache, projects: projectsCache } = useProjects();
  const [project, setProject] = useState<Project | null>(null);
  const [projectLoading, setProjectLoading] = useState(!!projectId && !conversationId);
  const [redactionEnabledState, setRedactionEnabledState] = useState(false);
  const redactionRef = useRef(redactionEnabledState);
  const missingConversationHandledRef = useRef<string | null>(null);
  const missingConversationRefreshAttemptRef = useRef<string | null>(null);
  const runtimeConversationId = conversationId ?? "__inactive__";
  const streamMeta = useConversationStreamMeta(runtimeConversationId);
  const inputGate = useConversationInputGate(runtimeConversationId);

  const setRedactionEnabled = useCallback((value: boolean | ((prev: boolean) => boolean)) => {
    const next = typeof value === "function" ? value(redactionRef.current) : value;
    redactionRef.current = next;
    setRedactionEnabledState(next);
    try { window.sessionStorage.setItem("assist:redactionEnabled", next ? "1" : "0"); } catch {}
    try { window.localStorage.setItem("assist:redactionEnabled", next ? "1" : "0"); } catch {}
  }, []);

  // Load persisted redaction state on mount
  useEffect(() => {
    try {
      const fromSession = typeof window !== "undefined" ? window.sessionStorage.getItem("assist:redactionEnabled") : null;
      const fromLocal = typeof window !== "undefined" ? window.localStorage.getItem("assist:redactionEnabled") : null;
      const raw = fromSession ?? fromLocal;
      if (raw === "1" || raw === "0") {
        const flag = raw === "1";
        redactionRef.current = flag;
        setRedactionEnabledState(flag);
      }
    } catch {}
  }, []);

  // Composer bridge: ChatView registers its send/resume handlers when mounted
  const [composerBridge, setComposerBridge] = useState<ComposerBridge | null>(null);
  const handleComposerBridge = useCallback((bridge: ComposerBridge | null) => {
    setComposerBridge(bridge);
  }, []);

  // Composer top slot: ChatView pushes suggestion UI into the persistent input card
  const [composerTopSlot, setComposerTopSlot] = useState<ReactNode>(null);

  // Fetch project details when on project home page (projectId but no conversationId)
  useEffect(() => {
    if (!projectId) { setProject(null); setProjectLoading(false); return; }
    if (conversationId) { setProjectLoading(false); return; }

    async function fetchProject() {
      if (!projectId) return;
      setProjectLoading(true);
      try {
        const data = await getProject(projectId);
        setProject(data);
      } catch (error) {
        addToast({
          type: "error",
          title: "Failed to load project",
          description: error instanceof Error ? error.message : "Project not found",
        });
        navigate("/");
      } finally {
        setProjectLoading(false);
      }
    }
    fetchProject();
  }, [projectId, conversationId, addToast, navigate]);

  useEffect(() => {
    if (!projectId) return;
    const entry = projectsCache?.find?.((item) => item.id === projectId);
    if (!entry) return;
    setProject((prev) => (prev ? { ...prev, ...entry } : entry));
  }, [projectId, projectsCache]);

  useEffect(() => {
    if (!projectId) return;
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ project?: Project | null }>).detail;
      const updated = detail?.project;
      if (updated && updated.id === projectId) setProject(updated);
    };
    window.addEventListener("frontend:projectUpdated", listener as EventListener);
    return () => window.removeEventListener("frontend:projectUpdated", listener as EventListener);
  }, [projectId]);

  // Listen for conversation creation events and update cache
  useEffect(() => {
    const handleConversationCreated = (event: Event) => {
      const customEvent = event as CustomEvent<{ conversation?: ConversationResponsePayload }>;
      const payload = customEvent.detail?.conversation;
      if (!payload?.id) return;

      const nowIso = new Date().toISOString();
      const normalized = conversationResponseToSummary({
        ...payload,
        created_at: payload.created_at || nowIso,
        updated_at: payload.updated_at || nowIso,
        last_message_at: payload.last_message_at || nowIso,
      });
      const summary = {
        ...normalized,
        title: normalized.title || DEFAULT_CONVERSATION_TITLE,
        updated_at: normalized.updated_at || nowIso,
        last_message_at: normalized.last_message_at || nowIso,
        owner_id: normalized.owner_id || payload.owner_id || "",
        owner_name: normalized.owner_name ?? payload.owner_name ?? null,
        owner_email: normalized.owner_email ?? payload.owner_email ?? null,
        is_owner: typeof normalized.is_owner === "boolean" ? normalized.is_owner : true,
        can_edit: typeof normalized.can_edit === "boolean" ? normalized.can_edit : true,
      };

      let existed = false;
      updateConversations((current) => {
        const result = upsertConversationSummary(current, summary);
        existed = result.existed;
        return result.next;
      });

      if (!existed && summary.project_id) {
        updateProjectCache((current) => {
          const idx = current.findIndex((p) => p.id === summary.project_id);
          if (idx === -1) return current;
          const next = current.slice();
          const projectEntry = next[idx];
          next[idx] = {
            ...projectEntry,
            conversation_count: (projectEntry.conversation_count ?? 0) + 1,
            updated_at: summary.updated_at,
          };
          return next;
        });
      }
    };

    window.addEventListener("frontend:conversationCreated", handleConversationCreated);
    return () => window.removeEventListener("frontend:conversationCreated", handleConversationCreated);
  }, [updateConversations, updateProjectCache]);

  const activeConversation = useMemo(() => {
    if (!conversationId) return null;
    return conversations.find((item) => item.id === conversationId) ?? null;
  }, [conversationId, conversations]);

  // Redirect if conversation belongs to a different user / was deleted
  useEffect(() => {
    if (!conversationId) {
      missingConversationHandledRef.current = null;
      missingConversationRefreshAttemptRef.current = null;
      return;
    }
    if (conversationsLoading || conversationsError) return;
    const existsForCurrentUser = conversations.some((item) => item.id === conversationId);
    const hasRecoverableRuntime =
      streamMeta.phase === "starting" ||
      streamMeta.phase === "streaming" ||
      streamMeta.phase === "completing" ||
      streamMeta.phase === "paused_for_input" ||
      inputGate.isPausedForInput;
    if (existsForCurrentUser) {
      missingConversationHandledRef.current = null;
      missingConversationRefreshAttemptRef.current = null;
      return;
    }
    if (hasRecoverableRuntime) {
      missingConversationHandledRef.current = null;
      missingConversationRefreshAttemptRef.current = null;
      return;
    }
    if (missingConversationRefreshAttemptRef.current !== conversationId) {
      missingConversationRefreshAttemptRef.current = conversationId;
      void refreshConversations();
      return;
    }
    if (missingConversationHandledRef.current === conversationId) return;
    missingConversationHandledRef.current = conversationId;
    navigate(projectId ? `/projects/${projectId}` : "/", { replace: true });
  }, [
    conversationId,
    conversations,
    conversationsLoading,
    conversationsError,
    inputGate.isPausedForInput,
    navigate,
    projectId,
    refreshConversations,
    streamMeta.phase,
  ]);

  // Page title
  useEffect(() => {
    const baseTitle = "assistant";
    if (!conversationId) { document.title = baseTitle; return; }
    const title = activeConversation?.title;
    document.title = title && !isDefaultConversationTitle(title)
      ? title
      : DEFAULT_CONVERSATION_TITLE;
  }, [conversationId, activeConversation?.title]);

  const showPersistentComposer = true;
  const composerMode = !conversationId ? "create" : "send";
  const composerHidden = conversationId ? composerBridge?.inputVisible === false : false;
  const [insightsOpen, setInsightsOpen] = useState(false);

  // Virtual keyboard tracking — only register listeners on mobile.
  const isMobile = useIsMobile();
  const { isKeyboardOpen } = useVirtualKeyboard(isMobile);

  useEffect(() => {
    if (!conversationId) { setInsightsOpen(false); setComposerTopSlot(null); }
  }, [conversationId]);

  const content = (
    !conversationId ? (
      <div className="flex flex-col flex-1 min-h-0 w-full">
        <ChatHeader conversationId={undefined} projectId={projectId} projectName={project?.name ?? null} project={project ?? null} />
        <div className="relative flex-1 min-h-0">
          <StartNewChat project={project} projectId={projectId} projectLoading={projectLoading} />
        </div>
      </div>
    ) : (
      <div className="flex flex-col flex-1 min-h-0 w-full">
        <InsightSidebarProvider>
          <ConversationInsightsLayout
            conversationId={conversationId}
            onInsightsOpenChange={setInsightsOpen}
            header={
              <ChatHeader
                conversationId={conversationId}
                projectId={projectId}
                projectName={project?.name ?? null}
                project={project ?? null}
              />
            }
          >
            <ChatView
              conversationId={conversationId}
              projectId={projectId}
              canEdit={activeConversation ? activeConversation.can_edit !== false : true}
              viewerIsOwner={activeConversation ? activeConversation.is_owner === true : true}
              requiresFeedback={activeConversation?.requires_feedback ?? false}
              contextUsage={activeConversation?.context_usage ?? null}
              conversationTitle={activeConversation?.title ?? null}
              redactionEnabled={redactionEnabledState}
              onRedactionChange={setRedactionEnabled}
              onComposerBridge={handleComposerBridge}
              onComposerTopSlot={setComposerTopSlot}
            />
          </ConversationInsightsLayout>
        </InsightSidebarProvider>
      </div>
    )
  );

  const shell = (
    <div
      className="relative flex w-full flex-col overflow-hidden"
      style={{
        ["--thread-max-width" as string]: "46rem",
        // h-full minus any unaccounted keyboard height (fallback for browsers
        // that don't support interactive-widget=resizes-content).
        height: "calc(100% - var(--keyboard-height, 0px))",
      }}
    >
      <div className="assist-shell-bg" aria-hidden />
      <div className="relative z-[1] flex flex-1 min-h-0 overflow-hidden">
        {content}
      </div>
      {showPersistentComposer && !composerHidden && (
        <div
          className={cn(
            "shrink-0 relative z-[2] px-3 pt-1 transition-[padding-right,padding-bottom] duration-200 ease-md-standard",
            conversationId && insightsOpen ? "md:pr-[calc(22rem+0.75rem)]" : "md:pr-3",
          )}
          style={{
            // On mobile, when the keyboard is open the browser viewport shrinks
            // so we don't need extra bottom padding — the composer naturally
            // sits above the keyboard. When closed, respect safe-area for
            // iPhone X+ home indicator.
            paddingBottom: isMobile
              ? isKeyboardOpen
                ? "0.25rem"
                : "calc(0.5rem + env(safe-area-inset-bottom, 0px))"
              : "0.5rem",
          }}
        >
          <div className="mx-auto max-w-[var(--thread-max-width,46rem)]">
            {composerMode === "create" ? (
              <ChatInput
                mode="create"
                projectId={projectId}
                redactionEnabled={redactionEnabledState}
                onRedactionChange={setRedactionEnabled}
                topContent={
                  !projectId
                    ? <UpcomingTasks variant="inline" bare />
                    : <ProjectRecentActivity projectId={projectId} bare />
                }
              />
            ) : composerBridge?.isPausedForInput && composerBridge.pausedInputPayload ? (
              <UserInputOverlay
                payload={composerBridge.pausedInputPayload}
                onSubmitted={composerBridge.resumePausedStream}
              />
            ) : composerBridge ? (
              <ChatInput
                mode="send"
                onSend={composerBridge.sendMessage}
                isStreaming={composerBridge.isStreaming}
                conversationId={conversationId}
                redactionEnabled={redactionEnabledState}
                onRedactionChange={setRedactionEnabled}
                topContent={composerTopSlot}
              />
            ) : (
              <ChatInput
                mode="send"
                onSend={async (_content, _options) => {}}
                disabled
                isStreaming={false}
                conversationId={conversationId}
                redactionEnabled={redactionEnabledState}
                onRedactionChange={setRedactionEnabled}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );

  if (projectId) {
    return (
      <FileDropProvider>
        <ProjectMembersProvider projectId={projectId}>
          {shell}
        </ProjectMembersProvider>
      </FileDropProvider>
    );
  }

  return <FileDropProvider>{shell}</FileDropProvider>;
};
