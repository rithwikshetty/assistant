
import { useCallback, useEffect, useMemo, useState, lazy, Suspense } from "react";
import { useAuth } from "@/contexts/auth-context";
import { StartPageLayout } from "@/components/chat/start-page-layout";
import { motion } from "framer-motion";
import { type Project } from "@/lib/api/projects-core";
import { ArrowRight, FolderSimple, ChatText, Sparkle } from "@phosphor-icons/react";
import { useConversations } from "@/hooks/use-conversations";
import { useNavigate } from "react-router-dom";
import { ProjectKnowledgeUploadButton } from "@/components/projects/project-knowledge-upload-button";
import { formatRelativeLabel, parseBackendDate } from "@/lib/datetime";
import { getRandomGreeting, type Greeting } from "@/lib/greetings";
import { Button } from "@/components/ui/button";
import { markdownComponents } from "@/components/markdown/markdown-components";
import { CollapsibleInlineList } from "@/components/ui/collapsible-inline-list";

type StartNewChatProps = {
  project?: Project | null;
  projectId?: string;
  projectLoading?: boolean;
};

const NEW_USER_STARTER_PROMPT =
  "I'm new to assistant. Walk me through getting started - ask me about my role and what I'm working on right now, then show me the most useful things I can do here based on my answers.";

export const StartNewChat: React.FC<StartNewChatProps> = ({
  project,
  projectId,
  projectLoading,
}) => {
  const { conversations, isLoading: conversationsLoading, error: conversationsError } = useConversations();

  useEffect(() => {
    try {
      const el = document.querySelector<HTMLTextAreaElement>('textarea[name="input"]');
      el?.focus();
    } catch { }
  }, []);

  const sendPromptDirectly = useCallback((prompt: string) => {
    const el = document.querySelector<HTMLTextAreaElement>('textarea[name="input"]');
    if (!el) return;

    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    nativeInputValueSetter?.call(el, prompt);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.focus({ preventScroll: true });

    requestAnimationFrame(() => {
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
    });
  }, []);

  const handleNewUserKickoff = useCallback(() => {
    sendPromptDirectly(NEW_USER_STARTER_PROMPT);
  }, [sendPromptDirectly]);

  const headerProjectId = projectId ?? project?.id ?? null;
  const headerProjectColor = project?.color ?? null;
  const currentProjectRole = project?.current_user_role ?? null;
  const canUploadKnowledge = Boolean(currentProjectRole);
  const showNewUserKickoffCta = !projectId && !conversationsLoading && !conversationsError && conversations.length === 0;

  if (projectId) {
    return (
      <StartPageLayout>
        <div className="flex h-full w-full max-w-[var(--thread-max-width)] flex-col overflow-hidden">
          <div className="flex flex-col justify-end pb-3 sm:pb-4 shrink-0 min-h-[60px] sm:min-h-[80px] md:min-h-0 md:flex-grow-[0.28] md:flex-shrink-0 md:basis-0">
            <WelcomeHeader
              projectId={headerProjectId}
              projectName={project?.name?.trim() ?? null}
              projectColor={headerProjectColor}
              projectLoading={projectLoading}
              canManageKnowledge={currentProjectRole === "owner"}
              canUploadKnowledge={canUploadKnowledge}
            />
          </div>
          <div className="flex-1 min-h-0 overflow-hidden md:flex-grow-[0.72] md:flex-shrink-0 md:basis-0">
            <div className="h-full overflow-y-auto scrollbar-none pt-3 sm:pt-5 pb-2 flex flex-col">
              <ProjectStartPanel
                project={project ?? null}
                loading={projectLoading}
              />
            </div>
          </div>
        </div>
      </StartPageLayout>
    );
  }

  return (
    <StartPageLayout>
      <div className="flex h-full w-full max-w-[var(--thread-max-width)] flex-col items-start justify-end pb-6 min-h-0">
        <WelcomeHeader
          projectId={null}
          projectName={null}
          projectColor={null}
          projectLoading={projectLoading}
          showNewUserKickoffCta={showNewUserKickoffCta}
          onNewUserKickoff={handleNewUserKickoff}
        />
      </div>
    </StartPageLayout>
  );
};

const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;

const LazyMarkdownBlock = lazy(() =>
  Promise.all([import("react-markdown"), import("remark-gfm")]).then(
    ([{ default: ReactMarkdown }, { default: remarkGfm }]) => ({
      default: ({ content, components }: { content: string; components: Record<string, unknown> }) => (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {content}
        </ReactMarkdown>
      ),
    }),
  ),
);

const ProjectMarkdownDescription: React.FC<{ content: string }> = ({ content }) => (
  <div className="aui-md type-size-12 leading-relaxed text-muted-foreground [&>*]:mb-1.5 [&>*:last-child]:mb-0">
    <Suspense fallback={<div className="h-4 w-3/4 animate-pulse rounded bg-muted/40" />}>
      <LazyMarkdownBlock content={content} components={markdownComponents} />
    </Suspense>
  </div>
);

const DESCRIPTION_MAX_PX = 260;

const ScrollableDescription: React.FC<{ content: string }> = ({ content }) => (
  <div
    className="rounded-lg border border-border/40 bg-muted/20 px-4 py-3 overflow-y-auto scrollbar-thin scrollbar-thumb-border/30 scrollbar-track-transparent"
    style={{ maxHeight: `${DESCRIPTION_MAX_PX}px` }}
  >
    <ProjectMarkdownDescription content={content} />
  </div>
);

const ProjectStartPanel: React.FC<{
  project: Project | null;
  loading?: boolean;
}> = ({ project, loading }) => {
  const trimmedDescription = (project?.description ?? "").trim();
  const hasDescription = trimmedDescription.length > 0;

  if (loading && !project) {
    return (
      <div className="space-y-2">
        <div className="h-10 rounded-lg bg-muted/40 animate-pulse" />
      </div>
    );
  }

  if (!hasDescription) return null;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <span className="type-overline mb-2 block">
          About
        </span>
        <ScrollableDescription content={trimmedDescription} />
      </div>
    </div>
  );
};

export const ProjectRecentActivity: React.FC<{ projectId: string; bare?: boolean }> = ({ projectId, bare = false }) => {
  const { conversations, isLoading } = useConversations();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [isExpanded, setIsExpanded] = useState(false);

  const currentUserId = user?.id ?? null;
  const currentUserEmail = user?.email?.toLowerCase() ?? null;

  const projectConversations = useMemo(() => {
    const cutoff = Date.now() - TWENTY_FOUR_HOURS_MS;
    const toMillis = (c: typeof conversations[number]) => {
      const ts = c.last_message_at ?? c.updated_at;
      if (!ts) return 0;
      const parsed = parseBackendDate(ts);
      if (!parsed) return 0;
      const ms = parsed.getTime();
      return Number.isFinite(ms) ? ms : 0;
    };
    return conversations
      .filter((c) => c.project_id === projectId)
      .filter((c) => { const ms = toMillis(c); return ms >= cutoff && ms > 0; })
      .sort((a, b) => toMillis(b) - toMillis(a));
  }, [projectId, conversations]);

  if (isLoading && projectConversations.length === 0) return null;
  if (projectConversations.length === 0) return null;

  return (
    <CollapsibleInlineList
      icon={<ChatText className="h-3.5 w-3.5 text-primary" />}
      label="Recent activity"
      overlayExpand={!bare}
      bare={bare}
      headerExtra={
        <span className="rounded-md bg-muted/50 px-1.5 py-0.5 type-size-10 text-muted-foreground/70 leading-none tabular-nums">
          {projectConversations.length}
        </span>
      }
      expanded={isExpanded}
      onToggle={() => setIsExpanded(!isExpanded)}
      scrollable
      maxHeight="12rem"
      className={bare ? undefined : "mb-2"}
    >
      {projectConversations.map((conversation) => {
        const lastTimestamp = conversation.last_message_at ?? conversation.updated_at ?? "";
        const relativeLabel = formatRelativeLabel(lastTimestamp) ?? "Recently";
        const ownerName = conversation.owner_name?.trim() ?? "";
        const ownerEmail = conversation.owner_email?.trim() ?? "";
        const ownerLabel = ownerName || ownerEmail;
        const ownerMatchesUser = (
          (conversation.owner_id && conversation.owner_id === currentUserId) ||
          (ownerEmail && currentUserEmail && ownerEmail.toLowerCase() === currentUserEmail)
        );

        return (
          <Button
            key={conversation.id}
            type="button"
            variant="ghost"
            onClick={() => navigate(`/projects/${projectId}/chat/${conversation.id}`)}
            className="group flex min-h-[2rem] w-full items-center justify-between gap-2 px-3.5 py-1.5 text-left transition-colors hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 h-auto rounded-none active:!scale-100"
          >
            <div className="flex-1 min-w-0">
              <span className="type-size-12 leading-relaxed truncate block text-foreground/85 group-hover:text-foreground">
                {conversation.title || "Untitled conversation"}
              </span>
              {ownerLabel && (
                <span className="type-size-10 text-muted-foreground/40 truncate block leading-tight">
                  {ownerMatchesUser ? "You" : ownerLabel}
                </span>
              )}
            </div>
            <span className="type-size-10 shrink-0 text-muted-foreground/50">
              {relativeLabel}
            </span>
          </Button>
        );
      })}
    </CollapsibleInlineList>
  );
};

/* ------------------------------------------------------------------ */
/*  WelcomeHeader                                                      */
/* ------------------------------------------------------------------ */

const WelcomeHeader: React.FC<{
  projectId?: string | null;
  projectName?: string | null;
  projectColor?: string | null;
  projectLoading?: boolean;
  canManageKnowledge?: boolean;
  canUploadKnowledge?: boolean;
  showNewUserKickoffCta?: boolean;
  onNewUserKickoff?: () => void;
}> = ({ projectId, projectName, projectColor, projectLoading, canManageKnowledge, canUploadKnowledge, showNewUserKickoffCta = false, onNewUserKickoff }) => {
  const { user, isAuthenticated, isBackendAuthenticated, isLoading } = useAuth();
  const rawFirstName = user?.name ? user.name.split(" ")[0] : "";
  const authenticated = !isLoading && isAuthenticated && isBackendAuthenticated;

  const [greeting] = useState<Greeting>(() => getRandomGreeting());

  // Treat generic placeholder names as "no name"
  const genericNames = new Set(["assistant", "user", "admin", "test"]);
  const firstName = genericNames.has(rawFirstName.toLowerCase()) ? "" : rawFirstName;
  const hasName = authenticated && !!firstName;
  const normalizedProjectName = projectName?.trim();
  const normalizedProjectColor = projectColor?.trim() || null;

  const showProjectContext = Boolean(projectId);
  const showProjectDetails = Boolean(projectId && normalizedProjectName);

  if (showProjectContext) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.05, 0.7, 0.1, 1] }}
        className="flex w-full max-w-[var(--thread-max-width)]"
      >
        <div className="flex w-full items-center justify-between gap-2 sm:gap-3">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3 flex-1">
            <div className="flex h-10 w-10 sm:h-12 sm:w-12 items-center justify-center rounded-xl bg-primary/8 border border-primary/10">
              <FolderSimple
                className="h-5 w-5 sm:h-6 sm:w-6 text-primary"
                style={normalizedProjectColor ? { color: normalizedProjectColor } : undefined}
                aria-hidden
              />
            </div>
            {showProjectDetails ? (
              <h1
                className="type-page-title truncate text-left"
                style={{ letterSpacing: '-0.02em' }}
                title={normalizedProjectName}
              >
                {normalizedProjectName}
              </h1>
            ) : (
              <div className="h-5 w-32 rounded bg-muted/80 animate-pulse" />
            )}
          </div>
          {showProjectDetails ? (
            <ProjectKnowledgeUploadButton
              projectId={projectId}
              projectName={normalizedProjectName ?? null}
              canManageKnowledge={canManageKnowledge}
              canUploadKnowledge={canUploadKnowledge}
              disabled={projectLoading}
            />
          ) : (
            <div className="h-10 w-10 sm:h-12 sm:w-12 rounded-xl border border-border/60 bg-muted/40 animate-pulse shrink-0" />
          )}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: [0.05, 0.7, 0.1, 1] }}
      className="flex w-full max-w-[var(--thread-max-width)] flex-col items-start gap-3"
    >
      {/* Greeting — editorial, left-aligned, typographic */}
      {projectLoading ? (
        <span className="type-size-14 text-muted-foreground/80">Loading project</span>
      ) : (
        <div className="flex flex-col gap-1">
          {hasName && (
            <motion.span
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="type-overline text-primary"
            >
              {greeting.template.includes("morning") ? "Good morning" :
               greeting.template.includes("afternoon") ? "Good afternoon" :
               greeting.template.includes("evening") ? "Good evening" :
               "Welcome back"}
            </motion.span>
          )}
          <motion.h1
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, delay: hasName ? 0.15 : 0.1 }}
            className="type-hero-title"
            style={{ letterSpacing: '-0.03em' }}
          >
            {hasName ? firstName : "What can I help with?"}
          </motion.h1>
          {hasName && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5, delay: 0.3 }}
              className="mt-1 type-size-16 text-muted-foreground/60 max-w-md"
            >
              What would you like to work on?
            </motion.p>
          )}
        </div>
      )}

      {showNewUserKickoffCta && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.45, ease: [0.05, 0.7, 0.1, 1] }}
          className="mt-3"
        >
          <button
            type="button"
            onClick={() => onNewUserKickoff?.()}
            className="group flex items-center gap-2.5 rounded-xl border border-primary/15 bg-primary/5 px-5 py-3 type-size-14 font-medium text-primary hover:bg-primary/10 hover:border-primary/25 transition-all duration-300 shadow-sm"
          >
            <Sparkle className="h-4 w-4 text-primary/70 group-hover:text-primary transition-colors" weight="fill" />
            Help me get started
            <ArrowRight className="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-1" />
          </button>
        </motion.div>
      )}
    </motion.div>
  );
};
