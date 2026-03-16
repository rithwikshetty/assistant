
import { FC, useCallback, useEffect, useMemo, useState, useRef } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Briefcase,
  FolderSimple,
  FolderOpen,
  DotsThree,
  SpinnerGap,
  PencilSimple,
  Trash,
  CheckSquare,
  Square,
  Lock,
  SlidersHorizontal,
  PushPin,
  CaretRight,
  CaretDown,
  GitBranch,
} from "@phosphor-icons/react";
import { useProjects } from "@/hooks/use-projects";
import { useConversations } from "@/hooks/use-conversations";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuAction,
} from "@/components/ui/sidebar";
import { CreateProjectDialog } from "@/components/projects/create-project-dialog";
import { EditProjectDialog } from "@/components/projects/edit-project-dialog";
import { ProjectSharingDialog } from "@/components/projects/project-sharing-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { InlineTitleEditor } from "@/components/navigation/inline-title-editor";
import { useToast } from "@/components/ui/toast";
import { deleteConversations, renameConversation, togglePinConversation, type ConversationSummary } from "@/lib/api/auth";
import { useSelection } from "@/contexts/selection-context";
import { conversationMatchesQuery } from "@/lib/search/conversation-cache-search";
import { useActiveStreams } from "@/contexts/active-streams-context";
import { useDroppable, useDraggable } from "@dnd-kit/core";
import { useConversationDragContext } from "./conversation-dnd-context";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useAuth } from "@/contexts/auth-context";
import { ProjectMembersProvider } from "@/contexts/project-members-context";
import { formatRelativeCompact } from "@/lib/datetime";
import { resolveConversationDisplayTitle } from "@/lib/conversation-titles";
import { performPinToggle } from "@/lib/navigation/pin-toggle";

const PROJECT_EXPANDED_STORAGE_KEY = "assist_sidebar_expanded_projects";
const SECTION_COLLAPSED_STORAGE_KEY = "assist_sidebar_collapsed_sections";

const SectionHeader: FC<{ label: string; isCollapsed: boolean; onToggle: () => void }> = ({ label, isCollapsed, onToggle }) => (
  <div
    role="button"
    tabIndex={0}
    onClick={onToggle}
    onKeyDown={(e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onToggle();
      }
    }}
    className="group type-nav-label px-2 pt-2.5 pb-0.5 flex items-center gap-1.5 cursor-pointer text-sidebar-foreground/40 hover:text-sidebar-foreground/60 transition-colors"
  >
    <span>{label}</span>
    {isCollapsed ? (
      <CaretRight className="size-3" />
    ) : (
      <CaretDown className="size-3 opacity-0 group-hover:opacity-100 transition-opacity" />
    )}
  </div>
);

const PROJECT_ROW_BASE_CLASSES =
  "h-8 gap-2 !rounded-[5.7px] hover:bg-muted/50 transition-colors duration-200";

interface ProjectDragContainerRenderArgs {
  setNodeRef: (node: HTMLElement | null) => void;
  isOver: boolean;
}

const ProjectDragContainer: FC<{
  projectId: string;
  children: (args: ProjectDragContainerRenderArgs) => ReactNode;
}> = ({ projectId, children }) => {
  const { setNodeRef, isOver } = useDroppable({
    id: `project-${projectId}`,
    data: { projectId },
  });

  return <>{children({ setNodeRef, isOver })}</>;
};

interface ProjectConversationRowProps {
  conversation: ConversationSummary;
  projectId: string;
  isActive: boolean;
  isOperating: boolean;
  isEditing: boolean;
  isSelected: boolean;
  inSelectionMode: boolean;
  isBulkDeleting: boolean;
  isTitlePending: boolean;
  isStreamActive: boolean;
  isStreamCompleted: boolean;
  isNewlyCreated: boolean;
  onRowClick: (() => void) | undefined;
  onToggleSelection: () => void;
  onStartRename: () => void;
  onSaveRename: (newTitle: string) => void;
  onCancelRename: () => void;
  onRequestDelete: () => void;
  onTogglePin: () => void;
  onGoToParent?: () => void;
}

const ProjectConversationRow: FC<ProjectConversationRowProps> = ({
  conversation,
  projectId,
  isActive,
  isOperating,
  isEditing,
  isSelected,
  inSelectionMode,
  isBulkDeleting,
  isTitlePending,
  isStreamActive,
  isStreamCompleted,
  isNewlyCreated,
  onRowClick,
  onToggleSelection,
  onStartRename,
  onSaveRename,
  onCancelRename,
  onRequestDelete,
  onTogglePin,
  onGoToParent,
}) => {
  const { moveInProgress: _moveInProgress } = useConversationDragContext();
  const canEdit = conversation.can_edit !== false;
  const dragDisabled = _moveInProgress || inSelectionMode || isEditing || isOperating || isBulkDeleting || !canEdit;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: conversation.id,
    data: { type: 'conversation', conversationId: conversation.id, fromProjectId: projectId },
    disabled: dragDisabled,
  });

  const draggableProps = dragDisabled ? {} : { ...listeners, ...attributes };
  const relativeTime = formatRelativeCompact(conversation.last_message_at || conversation.updated_at);
  const displayTitle = resolveConversationDisplayTitle(conversation);

  return (
    <SidebarMenuItem className={cn("group/menu-item relative", isDragging && "opacity-50")}>
      {inSelectionMode && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn(
            "absolute left-2 top-1/2 z-10 h-5 w-5 -translate-y-1/2 rounded border transition-colors",
            isSelected
              ? "border-transparent bg-sidebar-accent text-sidebar-accent-foreground"
              : "border-sidebar-border bg-sidebar text-sidebar-foreground/50",
            !canEdit && "opacity-50"
          )}
          disabled={!canEdit}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (!canEdit) return;
            onToggleSelection();
          }}
          aria-label={isSelected ? "Deselect chat" : "Select chat"}
          aria-pressed={isSelected}
          aria-disabled={!canEdit}
        >
          {isSelected ? <CheckSquare className="size-4" /> : <Square className="size-4" />}
        </Button>
      )}
      <div
        ref={setNodeRef}
        className="flex-1"
        {...draggableProps}
      >
        <SidebarMenuButton
          isActive={isActive}
          tooltip={!inSelectionMode && !isEditing ? displayTitle : undefined}
          onClick={onRowClick}
          aria-pressed={inSelectionMode ? isSelected : undefined}
          className={cn(
            "h-[31px] py-[7px] !rounded-[5.7px] data-[active=true]:font-normal border border-transparent active:scale-[0.98] data-[active=true]:bg-sidebar-accent transition-colors duration-200 ease-out",
            isNewlyCreated && "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-200 motion-safe:ease-out bg-accent-yellow/20 dark:bg-accent-yellow/15 border-accent-yellow/50",
            inSelectionMode ? "pl-10" : "",
            inSelectionMode && isSelected
              ? "border-sidebar-accent/60 bg-sidebar-accent/15 dark:bg-sidebar-accent/20"
              : undefined,
          )}
        >
          <div className="flex w-full items-center gap-2 overflow-hidden min-w-0">
            {/* Status indicator gutter — fixed-width so every title aligns */}
            <span className="shrink-0 w-4 inline-flex items-center justify-center">
              {/* Default indicators — hidden on hover to reveal pin action */}
              <span className={cn("inline-flex items-center justify-center", !inSelectionMode && "group-hover/menu-item:hidden")}>
                {(isTitlePending || isStreamActive) ? (
                  <SpinnerGap className="size-3.5 animate-spin text-sidebar-foreground/30" aria-hidden="true" />
                ) : (isStreamCompleted && !isActive) ? (
                  <span className="size-2 rounded-full bg-primary" aria-label="New response available" />
                ) : !conversation.is_owner ? (
                  <Avatar className="h-3.5 w-3.5 border border-border/40">
                    <AvatarFallback className="type-size-8 bg-sidebar-accent text-sidebar-foreground/70">
                      {getInitials((conversation.owner_name || conversation.owner_email || "").trim()).charAt(0)}
                    </AvatarFallback>
                  </Avatar>
                ) : conversation.is_pinned && !inSelectionMode ? (
                  <PushPin className="size-3 text-primary" aria-label="Pinned" />
                ) : null}
              </span>
              {/* Pin action — appears on hover, replaces any status indicator */}
              {!inSelectionMode && (
                <span
                  onClick={(e) => {
                    if (isOperating) return;
                    e.stopPropagation();
                    onTogglePin();
                  }}
                  className={cn(
                    "hidden group-hover/menu-item:inline-flex items-center justify-center",
                    isOperating ? "cursor-not-allowed opacity-50" : "cursor-pointer",
                  )}
                  role="button"
                  tabIndex={-1}
                  aria-label={conversation.is_pinned ? "Unpin chat" : "Pin chat"}
                >
                  <PushPin className={cn("size-3 transition-colors", conversation.is_pinned ? "text-sidebar-primary" : "text-sidebar-foreground/30 hover:text-sidebar-foreground/50")} />
                </span>
              )}
            </span>
            {conversation.parent_conversation_id && onGoToParent && (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  onGoToParent();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.stopPropagation();
                    e.preventDefault();
                    onGoToParent();
                  }
                }}
                className="shrink-0 inline-flex items-center justify-center rounded-sm text-primary/60 hover:text-primary dark:hover:text-primary focus-visible:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/30 transition-colors cursor-pointer"
                aria-label="Go to original conversation"
                title="Go to original conversation"
              >
                <GitBranch className="size-3.5" />
              </span>
            )}
            <InlineTitleEditor
              initialTitle={displayTitle}
              comparisonTitle={conversation.title}
              isEditing={isEditing}
              onSave={onSaveRename}
              onCancel={onCancelRename}
              className="flex-1 truncate min-w-0 type-nav-row"
              disabled={isOperating || inSelectionMode || isBulkDeleting || !canEdit}
            />
          </div>
        </SidebarMenuButton>
      </div>
      {/* Timestamp at the far right — fades out on hover when action buttons appear */}
      {!inSelectionMode && relativeTime && !isTitlePending && !isStreamActive && (
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 type-nav-meta tabular-nums text-sidebar-foreground/30 pointer-events-none transition-opacity duration-150 group-hover/menu-item:opacity-0 group-focus-within/menu-item:opacity-0 group-has-data-[state=open]/menu-item:opacity-0 group-data-[collapsible=icon]:hidden">
          {relativeTime}
        </span>
      )}
      {!inSelectionMode && !canEdit && (
        <SidebarMenuAction showOnHover className="!top-1/2 !-translate-y-1/2 w-6 h-6">
          <Lock className="size-4 text-sidebar-foreground/40" />
          <span className="sr-only">Read-only</span>
        </SidebarMenuAction>
      )}
      {!inSelectionMode && canEdit && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuAction showOnHover className="!top-1/2 !-translate-y-1/2 w-6 h-6">
              {isOperating ? (
                <SpinnerGap className="size-4 animate-spin" />
              ) : (
                <DotsThree className="size-4" />
              )}
              <span className="sr-only">More options</span>
            </SidebarMenuAction>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start">
            <DropdownMenuItem
              onClick={onStartRename}
              disabled={isOperating || isEditing || isBulkDeleting}
              className="focus:text-sidebar-foreground"
            >
              <PencilSimple className="size-4 mr-2" />
              Rename chat
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={onRequestDelete}
              disabled={isBulkDeleting}
              className="text-destructive focus:text-destructive"
            >
              <Trash className="size-4 mr-2" />
              Delete chat
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </SidebarMenuItem>
  );
};

function getInitials(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  if (trimmed.includes("@")) {
    return trimmed.slice(0, 2).toUpperCase();
  }
  return trimmed.slice(0, 2).toUpperCase();
}

export const ProjectList: FC<{ searchQuery?: string }> = ({ searchQuery = "" }) => {
  const { projects, isLoading, updateProjects } = useProjects();
  const { conversations, updateConversations } = useConversations();
  const navigate = useNavigate();
  const pathname = useLocation().pathname;
  const { addToast } = useToast();
  const { moveInProgress: _moveInProgress, activeDrag } = useConversationDragContext();
  const { user } = useAuth();
  const activeProjectId = useMemo(() => {
    if (!pathname) return null;
    const match = pathname.match(/^\/projects\/([^/]+)/);
    return match?.[1] ?? null;
  }, [pathname]);
  // Start with all projects collapsed on initial load/refresh for a cleaner UX
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set());
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditProjectDialog, setShowEditProjectDialog] = useState(false);
  const [projectToEdit, setProjectToEdit] = useState<typeof projects[0] | null>(null);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [operatingConversationId, setOperatingConversationId] = useState<string | null>(null);
  const [projectToManage, setProjectToManage] = useState<typeof projects[0] | null>(null);
  // Track conversations with active jobs (streaming) and recently completed - from shared context
  const { activeStreamIds, completedStreamIds, clearCompleted, markLocalComplete } = useActiveStreams();

  // Clear the blue "completed" dot when user navigates to that conversation
  const activeProjectConvMatch = pathname.match(/\/projects\/[^/]+\/chat\/([^/]+)/);
  const activeProjectConvId = activeProjectConvMatch?.[1] ?? null;
  useEffect(() => {
    if (activeProjectConvId && completedStreamIds.has(activeProjectConvId)) {
      clearCompleted(activeProjectConvId);
    }
  }, [activeProjectConvId, completedStreamIds, clearCompleted]);

  // Section collapse state - start with empty to avoid hydration mismatch
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set<string>());
  const [hasHydratedSections, setHasHydratedSections] = useState(false);
  const [recentlyCreatedIds, setRecentlyCreatedIds] = useState<Set<string>>(new Set<string>());
  const recentCreateTimersRef = useRef<Map<string, number>>(new Map());

  // Load collapsed sections from localStorage after mount
  useEffect(() => {
    if (typeof window !== "undefined" && !hasHydratedSections) {
      try {
        const raw = window.localStorage.getItem(SECTION_COLLAPSED_STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            setCollapsedSections(new Set(parsed.filter((id): id is string => typeof id === "string")));
          }
        }
      } catch {
        // Failed to read section collapse state
      }
      setHasHydratedSections(true);
    }
  }, [hasHydratedSections]);

  const toggleSection = useCallback((sectionKey: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionKey)) {
        next.delete(sectionKey);
      } else {
        next.add(sectionKey);
      }
      try {
        window.localStorage.setItem(SECTION_COLLAPSED_STORAGE_KEY, JSON.stringify([...next]));
      } catch {
        // Failed to save
      }
      return next;
    });
  }, []);

  // Track previous expanded state to prevent unnecessary transition retriggering
  const prevExpandedRef = useRef<Set<string>>(new Set());

  const {
    selectionMode,
    selectedProjectId,
    selectedIds,
    isBulkDeleting,
    hiddenIds,
    setIsBulkDeleting,
    setHiddenIds,
    toggleSelection,
    enterSelectionMode,
    exitSelectionMode,
  } = useSelection();

  const persistExpandedSet = useCallback((setToPersist: Set<string>) => {
    try {
      if (setToPersist.size === 0) {
        window.localStorage.removeItem(PROJECT_EXPANDED_STORAGE_KEY);
      } else {
        window.localStorage.setItem(
          PROJECT_EXPANDED_STORAGE_KEY,
          JSON.stringify(Array.from(setToPersist)),
        );
      }
    } catch (_error) {
      // Failed to persist project expansion state
    }
  }, []);

  // Track conversations grouped by project so we can render quickly without repeated filters.
  const conversationsByProject = useMemo(() => {
    const map = new Map<string, typeof conversations>();
    for (const conversation of conversations) {
      if (!conversation.project_id) continue;
      if (!map.has(conversation.project_id)) {
        map.set(conversation.project_id, []);
      }
      map.get(conversation.project_id)!.push(conversation);
    }
    return map;
  }, [conversations]);

  // Filter conversations by search query
  const filterConversationsBySearch = useCallback((convs: typeof conversations) => {
    if (!searchQuery.trim()) {
      return convs;
    }

    const query = searchQuery.toLowerCase();
    return convs.filter((conv) => conversationMatchesQuery(conv, query));
  }, [searchQuery]);


  // Remove stale project ids from the expanded set so persisted state stays clean.
  useEffect(() => {
    // Only validate when we have projects loaded
    if (isLoading || projects.length === 0) return;

    const validIds = new Set(projects.map((project) => project.id));
    setExpandedProjects((prev) => {
      let changed = false;
      const next = new Set<string>();
      prev.forEach((id) => {
        if (validIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      if (!changed) return prev;
      persistExpandedSet(next);
      return next;
    });
  }, [projects, isLoading, persistExpandedSet]);

  const setProjectExpanded = useCallback((projectId: string, shouldExpand: boolean) => {
    setExpandedProjects((prev) => {
      const alreadyExpanded = prev.has(projectId);
      if (alreadyExpanded === shouldExpand) {
        return prev;
      }
      const next = new Set(prev);
      if (shouldExpand) {
        next.add(projectId);
      } else {
        next.delete(projectId);
      }
      persistExpandedSet(next);
      return next;
    });
  }, [persistExpandedSet]);

  const toggleProject = useCallback((projectId: string) => {
    setExpandedProjects((prev) => {
      const shouldExpand = !prev.has(projectId);
      const next = new Set(prev);
      if (shouldExpand) {
        next.add(projectId);
      } else {
        next.delete(projectId);
      }
      persistExpandedSet(next);
      return next;
    });
  }, [persistExpandedSet]);

  // Auto-expand the active project based on the current route (only if it has conversations).
  useEffect(() => {
    if (!activeProjectId) return;
    const activeProjectConversations = conversationsByProject.get(activeProjectId);
    if (activeProjectConversations && activeProjectConversations.length > 0) {
      setProjectExpanded(activeProjectId, true);
    }
  }, [activeProjectId, conversationsByProject, setProjectExpanded]);

  // Auto-expand projects with matching conversations when searching
  useEffect(() => {
    if (!searchQuery.trim()) return;

    setExpandedProjects((prev) => {
      const next = new Set(prev);
      let changed = false;

      for (const project of projects) {
        const allProjectConversations = conversationsByProject.get(project.id) ?? [];
        const filteredConversations = filterConversationsBySearch(allProjectConversations);

        if (filteredConversations.length > 0 && !next.has(project.id)) {
          next.add(project.id);
          changed = true;
        }
      }

      return changed ? next : prev;
    });
  }, [searchQuery, projects, conversationsByProject, filterConversationsBySearch]);

  // Auto-expand projects when new chats are created.
  useEffect(() => {
    const timers = recentCreateTimersRef.current;
    const onConversationCreated = (event: Event) => {
      const detail = (event as CustomEvent<{ conversation?: { id?: string; project_id?: string | null } }>).detail;
      const conversationId = detail?.conversation?.id;
      const projectId = detail?.conversation?.project_id ?? null;

      if (projectId) {
        setProjectExpanded(projectId, true);
        if (conversationId) {
          setRecentlyCreatedIds((prev) => {
            if (prev.has(conversationId)) return prev;
            const next = new Set(prev);
            next.add(conversationId);
            return next;
          });

          const existingTimer = timers.get(conversationId);
          if (existingTimer) {
            window.clearTimeout(existingTimer);
          }

          const timeoutId = window.setTimeout(() => {
            timers.delete(conversationId);
            setRecentlyCreatedIds((prev) => {
              if (!prev.has(conversationId)) return prev;
              const next = new Set(prev);
              next.delete(conversationId);
              return next;
            });
          }, 1200);
          timers.set(conversationId, timeoutId);
        }
      }
    };

    window.addEventListener("frontend:conversationCreated", onConversationCreated as EventListener);

    return () => {
      window.removeEventListener("frontend:conversationCreated", onConversationCreated as EventListener);
      timers.forEach((timeoutId) => window.clearTimeout(timeoutId));
      timers.clear();
    };
  }, [setProjectExpanded]);

  useEffect(() => {
    const onConversationMoved = (event: Event) => {
      const detail = (event as CustomEvent<{ projectId?: string | null }>).detail;
      const projectId = detail?.projectId;
      if (projectId) {
        setProjectExpanded(projectId, true);
      }
    };
    window.addEventListener("frontend:conversationMoved", onConversationMoved as EventListener);
    return () => window.removeEventListener("frontend:conversationMoved", onConversationMoved as EventListener);
  }, [setProjectExpanded]);

  const handleProjectNavigate = useCallback(
    (projectId: string) => {
      setProjectExpanded(projectId, true);
      navigate(`/projects/${projectId}`);
    },
    [navigate, setProjectExpanded]
  );

  const handleSaveRename = useCallback(
    (conversationId: string, projectId: string, newTitle: string) => {
      setOperatingConversationId(conversationId);
      (async () => {
        try {
          await renameConversation(conversationId, newTitle);
          updateConversations((current) =>
            current.map((conversation) =>
              conversation.id === conversationId
                ? { ...conversation, title: newTitle, updated_at: new Date().toISOString() }
                : conversation
            )
          );
          updateProjects((current) =>
            current.map((project) =>
              project.id === projectId
                ? {
                    ...project,
                    updated_at: new Date().toISOString(),
                  }
                : project
            )
          );
          addToast({ type: "success", title: "Chat renamed" });
          setEditingConversationId(null);
        } catch (error) {
          addToast({
            type: "error",
            title: "Couldn't rename chat",
            description: error instanceof Error ? error.message : "Please try again.",
          });
        } finally {
          setOperatingConversationId(null);
        }
      })();
    },
    [addToast, updateConversations, updateProjects]
  );

  const handleTogglePin = useCallback((conversationId: string) => {
    performPinToggle({
      conversationId,
      updateItems: updateConversations,
      apiCall: togglePinConversation,
      setOperatingId: setOperatingConversationId,
      addToast,
    });
  }, [addToast, updateConversations]);

  const conversationById = useMemo(() => {
    const map = new Map<string, ConversationSummary>();
    for (const c of conversations) map.set(c.id, c);
    return map;
  }, [conversations]);

  const buildGoToParent = useCallback((conv: ConversationSummary) => {
    if (!conv.parent_conversation_id) return undefined;
    const parent = conversationById.get(conv.parent_conversation_id);
    if (!parent) return undefined;
    return () => {
      const dest = parent.project_id
        ? `/projects/${parent.project_id}/chat/${parent.id}`
        : `/chat/${parent.id}`;
      navigate(dest);
    };
  }, [conversationById, navigate]);

  const handleRequestDelete = useCallback((conversationId: string, projectId: string) => {
    enterSelectionMode('project', conversationId, projectId);
  }, [enterSelectionMode]);

  const handleEditProject = useCallback(
    (project: typeof projects[0]) => {
      setProjectToEdit(project);
      setShowEditProjectDialog(true);
    },
    []
  );

  const handleOpenManageProject = useCallback((project: typeof projects[0]) => {
    setProjectToManage(project);
  }, []);

  const handleCloseManageProject = useCallback(() => {
    setProjectToManage(null);
  }, []);

  useEffect(() => {
    const onRequestEdit = (event: Event) => {
      const detail = (event as CustomEvent<{ projectId?: string }>).detail;
      const projectId = detail?.projectId;
      if (!projectId) return;
      const target = projects.find((p) => p.id === projectId);
      if (!target) return;
      handleEditProject(target);
    };

    window.addEventListener("frontend:requestProjectEdit", onRequestEdit as EventListener);
    return () => window.removeEventListener("frontend:requestProjectEdit", onRequestEdit as EventListener);
  }, [projects, handleEditProject]);

  const handleBulkDelete = useCallback(
    async (projectId: string) => {
      if (selectedIds.size === 0 || isBulkDeleting) return;
      const ids = Array.from(selectedIds);
      setIsBulkDeleting(true);
      setHiddenIds((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.add(id));
        return next;
      });

      const activePath = typeof window !== 'undefined' ? window.location.pathname : '';
      const deletingActive = ids.some((id) => activePath === `/projects/${projectId}/chat/${id}`);

      try {
        const result = await deleteConversations(ids);
        const successfulIds = new Set<string>([
          ...(result.archived_ids ?? []),
          ...(result.already_archived_ids ?? []),
        ]);
        const failureIds = new Set<string>(result.not_found_ids ?? []);

        if (successfulIds.size > 0) {
          successfulIds.forEach((id) => {
            markLocalComplete(id);
          });
          updateConversations((current) => current.filter((conv) => !successfulIds.has(conv.id)));
          updateProjects((current) =>
            current.map((project) => {
              if (project.id !== projectId) return project;
              const deletedCount = Array.from(successfulIds).filter(id =>
                conversations.find(c => c.id === id)?.project_id === projectId
              ).length;
              const nextCount = Math.max((project.conversation_count ?? deletedCount) - deletedCount, 0);
              return {
                ...project,
                conversation_count: nextCount,
                updated_at: new Date().toISOString(),
              };
            })
          );
          if (deletingActive) {
            navigate(`/projects/${projectId}`);
          }
        }

        if (failureIds.size > 0) {
          addToast({
            type: 'error',
            title: 'Some chats not deleted',
            description: `${failureIds.size} chat${failureIds.size === 1 ? '' : 's'} could not be deleted.`,
          });
          // Keep selection mode active with failed IDs still selected
        } else {
          const archivedCount = successfulIds.size;
          exitSelectionMode();
          addToast({
            type: 'success',
            title: archivedCount > 1 ? 'Chats deleted' : 'Chat deleted',
            description: archivedCount > 1
              ? `${archivedCount} chats were deleted successfully.`
              : 'The conversation has been deleted successfully.',
          });
        }
      } catch (error) {
        // Failed to delete conversations
        addToast({
          type: 'error',
          title: 'Failed to delete chats',
          description: error instanceof Error ? error.message : 'An unexpected error occurred.',
        });
      } finally {
        setIsBulkDeleting(false);
        setHiddenIds((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }
    },
    [addToast, conversations, isBulkDeleting, markLocalComplete, navigate, selectedIds, updateConversations, updateProjects, setIsBulkDeleting, setHiddenIds, exitSelectionMode]
  );

  // Wire up the global delete button to trigger deletion
  useEffect(() => {
    if (selectionMode !== 'project' || !selectedProjectId) return;

    const handleGlobalDelete = () => {
      handleBulkDelete(selectedProjectId);
    };

    const deleteButton = document.getElementById('global-delete-button');
    if (deleteButton) {
      deleteButton.addEventListener('click', handleGlobalDelete);
      return () => deleteButton.removeEventListener('click', handleGlobalDelete);
    }
  }, [selectionMode, selectedProjectId, handleBulkDelete]);

  const renderProjectItems = (projectList: typeof projects) => projectList.map((project) => {
        const allProjectConversations = conversationsByProject.get(project.id) ?? [];
        const filteredConversations = filterConversationsBySearch(allProjectConversations);
        const projectConversations = filteredConversations
          .filter(conv => !hiddenIds.has(conv.id))
          .sort((a, b) => {
            // Pinned first by pinned_at desc, then by last_message_at desc as fallback
            const aPinned = a.is_pinned ? 1 : 0;
            const bPinned = b.is_pinned ? 1 : 0;
            if (aPinned !== bPinned) return bPinned - aPinned;
            const aTime = (a.pinned_at || a.last_message_at || a.updated_at);
            const bTime = (b.pinned_at || b.last_message_at || b.updated_at);
            return (bTime > aTime ? 1 : bTime < aTime ? -1 : 0);
          });
        const isExpanded = expandedProjects.has(project.id);
        const wasExpanded = prevExpandedRef.current.has(project.id);
        const isProjectActive = pathname === `/projects/${project.id}`;
        const inSelectionMode = selectionMode === 'project' && selectedProjectId === project.id;

        // Hide projects with no matching conversations when searching
        if (searchQuery.trim() && projectConversations.length === 0) {
          return null;
        }

        // Update the ref after reading it
        if (isExpanded !== wasExpanded) {
          if (isExpanded) {
            prevExpandedRef.current.add(project.id);
          } else {
            prevExpandedRef.current.delete(project.id);
          }
        }

        const isProjectOperating = projectToEdit?.id === project.id;
        const isProjectOwner =
          project.current_user_role === 'owner' || (user?.id ? user.id === project.user_id : false);
        const isConversationDraggingFromProject =
          activeDrag?.type === 'conversation' && activeDrag.fromProjectId === project.id;

        return (
          <ProjectDragContainer key={project.id} projectId={project.id}>
            {({ setNodeRef, isOver }) => (
              <div
                ref={setNodeRef}
                className={cn(
                  "rounded-xl transition-colors",
                  isOver && "bg-sidebar-accent/10 border border-sidebar-accent/40",
                )}
              >
                <SidebarMenuItem className="group/menu-item">
                  <SidebarMenuButton
                    onClick={() => handleProjectNavigate(project.id)}
                    isActive={isProjectActive}
                    className={cn(
                      PROJECT_ROW_BASE_CLASSES,
                      // Ensure clear highlight in both themes
                      "data-[active=true]:bg-sidebar-accent"
                    )}
                    data-expanded={isExpanded}
                  >
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        toggleProject(project.id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          event.stopPropagation();
                          toggleProject(project.id);
                        }
                      }}
                      className={cn(
                        "relative flex size-4 items-center justify-center text-sidebar-foreground/50 transition-transform duration-200 ease-out cursor-pointer translate-y-[1px]",
                        isExpanded && "scale-110"
                      )}
                      aria-label={isExpanded ? "Collapse project" : "Expand project"}
                      aria-expanded={isExpanded}
                    >
                      <FolderSimple
                        className={cn(
                          "absolute inset-0 size-4 transition-all duration-200 ease-out",
                          isExpanded ? "scale-0 opacity-0" : "scale-100 opacity-100"
                        )}
                        style={project.color ? { color: project.color } : undefined}
                      />
                      <FolderOpen
                        className={cn(
                          "absolute inset-0 size-4 transition-all duration-200 ease-out",
                          isExpanded ? "scale-100 opacity-100" : "scale-90 opacity-0"
                        )}
                        style={project.color ? { color: project.color } : undefined}
                      />
                    </div>
                    <span className="type-nav-row truncate text-sidebar-foreground flex-1 min-w-0">{project.name}</span>
                  </SidebarMenuButton>
                  {/* Show three-dot menu for every project; owners also get edit/manage shortcuts */}
                  {
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <SidebarMenuAction
                          showOnHover
                          className={cn(
                            "!top-1/2 !-translate-y-1/2 w-5 h-5",
                          )}
                        >
                          {isProjectOperating ? (
                            <SpinnerGap className="size-3.5 animate-spin" />
                          ) : (
                            <DotsThree className="size-4" />
                          )}
                          <span className="sr-only">More options</span>
                        </SidebarMenuAction>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent side="right" align="start">
                        {isProjectOwner && (
                          <DropdownMenuItem
                            onClick={() => handleEditProject(project)}
                            disabled={isProjectOperating || isBulkDeleting}
                            className="focus:text-sidebar-foreground"
                          >
                            <PencilSimple className="size-4 mr-2" />
                            Edit details
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                          onClick={() => handleOpenManageProject(project)}
                          disabled={isBulkDeleting}
                          className="focus:text-sidebar-foreground"
                        >
                          <SlidersHorizontal className="size-4 mr-2" />
                          Manage
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  }
                </SidebarMenuItem>

                <div
                  className={cn(
                    "space-y-0",
                    isExpanded !== wasExpanded && "transition-all duration-300 ease-in-out",
                    isExpanded ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0",
                    isOver && "bg-sidebar-accent/5",
                    isConversationDraggingFromProject ? "overflow-visible" : "overflow-hidden",
                  )}
                >
              {projectConversations.length > 0 ? (
                projectConversations.map((conversation) => {
                  const isActive = pathname === `/projects/${project.id}/chat/${conversation.id}`;
                  const isOperating = operatingConversationId === conversation.id;
                  const isEditing = editingConversationId === conversation.id;
                  const isSelected = selectedIds.has(conversation.id);
                  const canEdit = conversation.can_edit !== false;
                  const isStreamActive = activeStreamIds.has(conversation.id);
                  const isStreamCompleted = completedStreamIds.has(conversation.id);
                  const handleRowClick = inSelectionMode
                    ? (canEdit ? () => toggleSelection(conversation.id) : undefined)
                    : isEditing
                      ? undefined
                      : () => {
                          setProjectExpanded(project.id, true);
                          navigate(`/projects/${project.id}/chat/${conversation.id}`);
                        };

                  return (
                    <ProjectConversationRow
                      key={conversation.id}
                      conversation={conversation}
                      projectId={project.id}
                      isActive={isActive}
                      isOperating={isOperating}
                      isEditing={isEditing}
                      isSelected={isSelected}
                      inSelectionMode={inSelectionMode}
                      isBulkDeleting={isBulkDeleting}
                      isTitlePending={false}
                      isStreamActive={isStreamActive}
                      isStreamCompleted={isStreamCompleted}
                      isNewlyCreated={recentlyCreatedIds.has(conversation.id)}
                      onRowClick={handleRowClick}
                      onToggleSelection={() => toggleSelection(conversation.id)}
                      onStartRename={() => setEditingConversationId(conversation.id)}
                      onSaveRename={(newTitle) => handleSaveRename(conversation.id, project.id, newTitle)}
                      onCancelRename={() => setEditingConversationId(null)}
                      onRequestDelete={() => handleRequestDelete(conversation.id, project.id)}
                      onTogglePin={() => handleTogglePin(conversation.id)}
                      onGoToParent={buildGoToParent(conversation)}
                    />
                  );
                })
              ) : (
                <div className="py-1.5 px-3 type-nav-meta text-sidebar-foreground/40">
                  No conversations yet
                </div>
              )}
                </div>
              </div>
            )}
          </ProjectDragContainer>
        );
      }).filter((node): node is React.JSX.Element => Boolean(node));

  if (isLoading) {
    return null;
  }

  const projectNodes = renderProjectItems(projects);
  const isProjectsCollapsed = collapsedSections.has("projects");

  return (
    <>
      <SectionHeader
        label="Projects"
        isCollapsed={isProjectsCollapsed}
        onToggle={() => toggleSection("projects")}
      />

      {!isProjectsCollapsed && (
        <>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => setShowCreateDialog(true)}
              className={PROJECT_ROW_BASE_CLASSES}
            >
              <Briefcase className="size-4 text-sidebar-foreground/40 translate-y-[1px]" />
              <span className="type-nav-row text-sidebar-foreground/50">New project</span>
            </SidebarMenuButton>
          </SidebarMenuItem>

          {projectNodes}
          {projectNodes.length === 0 && (
            <div className="px-3 py-1.5 type-nav-meta text-sidebar-foreground/40">
              {searchQuery.trim()
                ? "No projects match your search."
                : "Create a project to get started."}
            </div>
          )}
        </>
      )}

      <CreateProjectDialog open={showCreateDialog} onClose={() => setShowCreateDialog(false)} />
      <EditProjectDialog
        open={showEditProjectDialog}
        onClose={() => {
          setShowEditProjectDialog(false);
          setProjectToEdit(null);
        }}
        project={projectToEdit}
      />
      {projectToManage ? (
        <ProjectMembersProvider projectId={projectToManage.id}>
          <ProjectSharingDialog
            open={Boolean(projectToManage)}
            onClose={handleCloseManageProject}
            projectId={projectToManage.id}
            projectName={projectToManage.name ?? undefined}
          />
        </ProjectMembersProvider>
      ) : null}
    </>
  );
};
