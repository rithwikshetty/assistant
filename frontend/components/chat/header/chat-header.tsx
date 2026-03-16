import { useMemo, useState, useEffect } from "react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useConversations } from "@/hooks/use-conversations";
import { useProjects } from "@/hooks/use-projects";
import { TooltipIconButton } from "@/components/tools/tooltip-icon-button";
import { GitBranch, GearSix, PencilSimple, FolderSimple } from "@phosphor-icons/react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { type Project } from "@/lib/api/projects-core";
import { ProjectSharingDialog } from "@/components/projects/project-sharing-dialog";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { type ProjectMember } from "@/lib/api/project-sharing";
import { useAuth } from "@/contexts/auth-context";
import { useProjectMembersContext } from "@/contexts/project-members-context";
import { tryClipboardWrite } from "@/lib/share-helpers";
import { resolveContextTokensUsed } from "@/lib/chat/context-usage";
import { MemoryUsageRing } from "./memory-usage-ring";
import { ConversationActionsDropdown } from "./conversation-actions-dropdown";
import { ProjectMemberAvatars } from "./project-member-avatars";
import { useConversationActions } from "./use-conversation-actions";
import { getInitials } from "./utils";

type ChatHeaderProps = {
  conversationId?: string;
  projectId?: string;
  projectName?: string | null;
  project?: Project | null;
};

export const ChatHeader = ({
  conversationId,
  projectId,
  projectName,
  project,
}: ChatHeaderProps) => {
  const { user } = useAuth();
  const isAdmin = (user?.role || "").toUpperCase() === "ADMIN";
  const { conversations, isLoading: isConversationsLoading, refreshConversations, updateConversations } = useConversations();
  const { addToast } = useToast();
  const projectMembers = useProjectMembersContext();
  const { projects: projectsList } = useProjects();

  const isProjectHome = Boolean(projectId && !conversationId);
  const isProjectConversation = Boolean(projectId && conversationId);

  const currentConversation = useMemo(() => {
    if (!conversationId) return undefined;
    return conversations.find((c) => c.id === conversationId);
  }, [conversationId, conversations]);

  // Hydration guard to avoid SSR/CSR mismatches on owner-dependent UI
  const [isHydrated, setIsHydrated] = useState(false);
  useEffect(() => { setIsHydrated(true); }, []);
  const viewerIsOwner = isHydrated ? currentConversation?.is_owner === true : false;
  const viewerIsProjectOwner = isHydrated && projectMembers?.isOwner === true;

  const isProjectMembersLoading = Boolean(projectId && (!projectMembers || projectMembers.isLoading));
  const sortedProjectMembers = useMemo<ProjectMember[]>(() => {
    if (!projectId || !projectMembers?.members?.length) return [];
    return [...projectMembers.members].sort((a, b) => {
      if (a.role === "owner" && b.role !== "owner") return -1;
      if (b.role === "owner" && a.role !== "owner") return 1;
      const nameA = (a.user_name || a.user_email || "").toLocaleLowerCase();
      const nameB = (b.user_name || b.user_email || "").toLocaleLowerCase();
      return nameA.localeCompare(nameB);
    });
  }, [projectId, projectMembers?.members]);

  const conversationOwnerMember = useMemo(() => {
    if (!currentConversation?.owner_id) return projectMembers?.primaryOwner ?? null;
    if (projectMembers?.members) {
      const match = projectMembers.members.find((m) => m.user_id === currentConversation.owner_id);
      if (match) return match;
    }
    return null;
  }, [currentConversation?.owner_id, projectMembers]);

  const ownerDisplayName = (conversationOwnerMember?.user_name || currentConversation?.owner_name || "").trim();
  const ownerDisplayEmail = conversationOwnerMember?.user_email || currentConversation?.owner_email || "";
  const ownerNameOrEmail = ownerDisplayName || ownerDisplayEmail;
  const ownerInitials = getInitials(ownerNameOrEmail || conversationOwnerMember?.user_email || "Owner");
  const currentConversationProjectId = currentConversation?.project_id ?? null;

  const projectFromList = useMemo(() => {
    if (!projectId) return null;
    return (projectsList || []).find((p) => p.id === projectId) ?? null;
  }, [projectsList, projectId]);

  const actions = useConversationActions({
    conversationId,
    projectId,
    project: project ?? null,
    currentConversationProjectId,
    conversations,
    viewerIsOwner,
    refreshConversations,
    updateConversations,
    addToast,
    isAdmin,
  });

  const { conversationUsage, setShowInstructions } = actions;

  const usageBadge = useMemo(() => {
    if (!conversationId || !conversationUsage) return null;
    const maxTokens = conversationUsage.max_context_tokens ?? null;
    if (!maxTokens || maxTokens <= 0) return null;
    const usedTokensRaw = resolveContextTokensUsed(conversationUsage);
    if (usedTokensRaw === null) return null;
    const usedTokens = Math.min(usedTokensRaw, maxTokens);
    const percent = Math.min(100, Math.max(0, Math.round((usedTokens / maxTokens) * 100)));

    let colorClass = "text-muted-foreground";
    if (percent >= 75) colorClass = "text-red-500 dark:text-red-400";
    else if (percent >= 45) colorClass = "text-amber-500 dark:text-amber-400";

    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={`inline-flex items-center gap-1 rounded-full bg-muted/40 px-1.5 sm:px-2.5 py-0.5 sm:py-1 type-chat-chip whitespace-nowrap ${colorClass}`}>
            <MemoryUsageRing percent={percent} className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
            <span className="hidden sm:inline">{percent}% memory used</span>
            <span className="sm:hidden">{percent}%</span>
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="center">
          {`${usedTokens.toLocaleString()} of ${maxTokens.toLocaleString()} tokens`}
        </TooltipContent>
      </Tooltip>
    );
  }, [conversationId, conversationUsage]);

  const instructionsBadge = useMemo(() => {
    const source = project ?? projectFromList;
    const has = Boolean(source?.custom_instructions && source.custom_instructions.trim());
    if (!has) return null;
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setShowInstructions(true)}
            className="inline-flex items-center gap-1 rounded-full bg-muted/40 px-1.5 sm:px-2.5 py-0.5 sm:py-1 h-auto type-chat-chip text-muted-foreground hover:bg-muted/70 ring-1 ring-transparent hover:ring-ring/30 whitespace-nowrap"
          >
            <span className="hidden sm:inline">Instructions</span>
            <span className="sm:hidden">Info</span>
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="center">
          View project instructions applied to the AI prompt
        </TooltipContent>
      </Tooltip>
    );
  }, [project, projectFromList, setShowInstructions]);

  return (
    <>
      {/* Fixed header on mobile, normal flow on desktop */}
      <header className="flex h-12 sm:h-14 shrink-0 items-center gap-1.5 sm:gap-2 px-2 sm:px-4 border-b border-border/30 bg-background/90 backdrop-blur-md fixed top-0 left-0 right-0 z-30 sm:relative sm:z-20">
        <div className="sm:hidden shrink-0">
          <SidebarTrigger className="min-h-9 min-w-9 p-1.5" />
        </div>

        {(conversationId || projectId) ? (
          <div className="flex items-center min-w-0 flex-1 gap-2.5 sm:gap-3">
            <h1 className="select-none type-chat-header-title truncate shrink-0">
              assistant
            </h1>
            {isProjectConversation && projectName && (
              <>
                <span className="text-border/60 type-control select-none shrink-0">/</span>
                <div className="flex items-center gap-1.5 min-w-0 rounded-md px-2 py-0.5 bg-muted/30 ring-1 ring-border/20">
                  <FolderSimple
                    className="h-3 w-3 sm:h-3.5 sm:w-3.5 shrink-0 text-muted-foreground"
                    style={(project ?? projectFromList)?.color ? { color: (project ?? projectFromList)!.color! } : undefined}
                    aria-hidden
                  />
                  <span className="type-control text-foreground/80 truncate">{projectName}</span>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="flex-1" />
        )}

        {/* Right: actions */}
        <div className="ml-auto flex items-center gap-1 sm:gap-2 shrink-0">
          {conversationId && usageBadge}
          {projectId && instructionsBadge}

          {/* Instructions modal */}
          <Modal
            open={actions.showInstructions}
            onClose={() => actions.setShowInstructions(false)}
            title="Project Instructions"
          >
            <div className="space-y-3">
              {(project ?? projectFromList)?.custom_instructions?.trim() ? (
                <>
                  <div className="rounded-xl border border-border/60 bg-muted/30 p-3 type-body whitespace-pre-wrap break-words text-foreground/90 max-h-80 overflow-auto">
                    {(project ?? projectFromList)?.custom_instructions}
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button type="button" variant="secondary" onClick={() => actions.setShowInstructions(false)}>
                      Close
                    </Button>
                    <Button
                      type="button"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText((project ?? projectFromList)?.custom_instructions || "");
                          addToast({ type: "success", title: "Copied to clipboard" });
                        } catch {
                          addToast({ type: "error", title: "Copy failed" });
                        }
                      }}
                    >
                      Copy
                    </Button>
                  </div>
                </>
              ) : (
                <p className="type-body-muted">No instructions set for this project.</p>
              )}
            </div>
          </Modal>

          {/* Share fallback modal */}
          <Modal
            open={actions.shareFallbackOpen}
            onClose={() => actions.setShareFallbackOpen(false)}
            title="Share Link"
          >
            <div className="space-y-3">
              <p className="type-body-muted">Copy and share this link. It expires in 7 days.</p>
              <div className="flex items-center gap-2">
                <Input
                  value={actions.shareFallbackUrl ?? ""}
                  readOnly
                  className="type-control-compact"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={async () => {
                    if (!actions.shareFallbackUrl) return;
                    const ok = await tryClipboardWrite(actions.shareFallbackUrl);
                    addToast(ok ? { type: "success", title: "Link copied" } : { type: "error", title: "Copy failed" });
                  }}
                >
                  Copy
                </Button>
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={() => actions.setShareFallbackOpen(false)}>
                  Close
                </Button>
              </div>
            </div>
          </Modal>

          {/* Project home actions */}
          {isProjectHome ? (
            <div className="flex items-center gap-2">
              <ProjectMemberAvatars
                allMembers={sortedProjectMembers}
                isLoading={isProjectMembersLoading}
              />
              {projectMembers?.isOwner ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-7 sm:h-8 px-1.5 sm:px-2 type-control-compact gap-1 sm:gap-1.5 text-muted-foreground hover:text-foreground hover:bg-muted/40"
                      onClick={actions.handleRequestEditProject}
                    >
                      <PencilSimple className="h-3 w-3 sm:h-3.5 sm:w-3.5 shrink-0" />
                      <span className="hidden sm:inline">Edit details</span>
                      <span className="sm:hidden">Edit</span>
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    Update the project name, description, and instructions
                  </TooltipContent>
                </Tooltip>
              ) : null}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-7 sm:h-8 px-1.5 sm:px-2 type-control-compact gap-1 sm:gap-1.5 text-muted-foreground hover:text-foreground hover:bg-muted/40"
                    onClick={() => actions.setIsProjectDialogOpen(true)}
                  >
                    <GearSix className="h-3 w-3 sm:h-3.5 sm:w-3.5 shrink-0" />
                    <span className="hidden sm:inline">Manage</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  Invite teammates and manage project members
                </TooltipContent>
              </Tooltip>
            </div>
          ) : null}

          {/* Project conversation actions */}
          {isProjectConversation ? (
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Avatar className="h-6 w-6 sm:h-8 sm:w-8">
                    <AvatarFallback className="bg-primary/10 text-primary dark:bg-[color:var(--primary-surface)] dark:text-[color:var(--primary-surface-foreground)] type-control-compact leading-none px-0.5">
                      {ownerInitials}
                    </AvatarFallback>
                  </Avatar>
                </TooltipTrigger>
                <TooltipContent side="bottom" align="center">
                  {ownerNameOrEmail || "Conversation owner"}
                </TooltipContent>
              </Tooltip>
              <ConversationActionsDropdown
                onShare={actions.handleShare}
                onBranch={actions.handleBranchFromLast}
                isSharing={actions.isSharing}
                isBranching={actions.isBranching}
                isHydrated={isHydrated}
                viewerIsOwner={viewerIsOwner}
              />
              {viewerIsProjectOwner ? (
                <TooltipIconButton
                  tooltip="Edit project details"
                  aria-label="Edit project details"
                  sizeClass="compact"
                  onClick={actions.handleRequestEditProject}
                  className="group"
                >
                  <PencilSimple className="h-5 w-5 transition-transform" />
                </TooltipIconButton>
              ) : null}
            </div>
          ) : null}

          {/* Non-project conversation actions */}
          {!isProjectConversation && conversationId ? (
            <ConversationActionsDropdown
              onShare={actions.handleShare}
              onBranch={actions.handleBranchFromLast}
              isSharing={actions.isSharing}
              isBranching={actions.isBranching}
              isHydrated={isHydrated}
              viewerIsOwner={viewerIsOwner}
            />
          ) : null}

          {/* Branch origin indicator */}
          {actions.parentConversationId && actions.hasParentConversation ? (
            <TooltipIconButton
              tooltip="Go to original conversation"
              aria-label="Go to original conversation"
              sizeClass="compact"
              onClick={actions.goToOriginal}
              className="group border border-border/50 text-muted-foreground hover:text-foreground hover:border-border hover:bg-muted/40"
            >
              <GitBranch className="h-5 w-5 transition-transform group-hover:scale-105" />
            </TooltipIconButton>
          ) : null}
          {actions.parentConversationId && !actions.hasParentConversation && !isConversationsLoading ? (
            <TooltipIconButton
              tooltip="Original conversation was deleted"
              aria-label="Original conversation was deleted"
              sizeClass="compact"
              disabled
              className="border border-dashed border-border/40 text-muted-foreground/40 cursor-default"
            >
              <GitBranch className="h-5 w-5" />
            </TooltipIconButton>
          ) : null}
        </div>

        {isProjectHome && projectId ? (
          <ProjectSharingDialog
            open={actions.isProjectDialogOpen}
            onClose={() => actions.setIsProjectDialogOpen(false)}
            projectId={projectId}
            projectName={projectName}
          />
        ) : null}
      </header>
      {/* Spacer for fixed header on mobile */}
      <div className="h-12 shrink-0 sm:hidden" aria-hidden="true" />
    </>
  );
};
