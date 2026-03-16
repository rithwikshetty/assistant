
import { FC, useState, useCallback, useMemo, useEffect, useRef } from "react";
import { DotsThree, Trash, SpinnerGap, PencilSimple, Warning, CheckSquare, Square, PushPin, CaretRight, CaretDown, User, GitBranch } from "@phosphor-icons/react";
import { useLocation, useNavigate } from "react-router-dom";
import { useConversations } from "@/hooks/use-conversations";
import { deleteConversations, renameConversation, togglePinConversation, type ConversationSummary } from "@/lib/api/auth";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { InlineTitleEditor } from "./inline-title-editor";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { SidebarMenuItem, SidebarMenuButton, SidebarMenuAction } from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { conversationMatchesQuery } from "@/lib/search/conversation-cache-search";
import { useActiveStreams } from "@/contexts/active-streams-context";
import { useSelection } from "@/contexts/selection-context";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useConversationDragContext } from "./conversation-dnd-context";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { parseBackendDate, formatRelativeCompact } from "@/lib/datetime";
import { resolveConversationDisplayTitle } from "@/lib/conversation-titles";
import { performPinToggle } from "@/lib/navigation/pin-toggle";

const formatRetryAfter = (seconds?: number): string => {
  if (!seconds || !Number.isFinite(seconds)) {
    return 'a few moments';
  }
  if (seconds < 60) {
    const rounded = Math.max(1, Math.round(seconds));
    return `${rounded} second${rounded === 1 ? '' : 's'}`;
  }
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} minute${minutes > 1 ? 's' : ''}`;
};

// Helper to categorize conversations by time period (in user's local timezone)
const categorizeByTime = (dateStr: string): 'today' | 'yesterday' | 'this_week' | 'older' => {
  const messageDate = parseBackendDate(dateStr);
  if (!messageDate) return 'older';
  const now = new Date();

  // Compare date strings (automatically uses user's timezone)
  const messageDateOnly = messageDate.toDateString();
  const todayDateOnly = now.toDateString();
  const yesterdayDateOnly = new Date(now.getTime() - 86400000).toDateString();

  if (messageDateOnly === todayDateOnly) return 'today';
  if (messageDateOnly === yesterdayDateOnly) return 'yesterday';

  // Check if it's within the last 7 days (this week)
  const sevenDaysAgo = new Date(now.getTime() - 7 * 86400000);
  if (messageDate >= sevenDaysAgo) return 'this_week';

  return 'older';
};

// Section header component
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
    className="group type-nav-label px-2 pt-2 pb-0.5 flex items-center gap-1.5 cursor-pointer text-sidebar-foreground/40 hover:text-sidebar-foreground/60 transition-colors"
  >
    <span>{label}</span>
    {isCollapsed ? (
      <CaretRight className="size-3" />
    ) : (
      <CaretDown className="size-3 opacity-0 group-hover:opacity-100 transition-opacity" />
    )}
  </div>
);

interface GeneralConversationRowProps {
  conversation: ConversationSummary;
  isActive: boolean;
  isOperating: boolean;
  isEditing: boolean;
  isSelected: boolean;
  inSelectionMode: boolean;
  isBulkDeleting: boolean;
  isTitlePending: boolean;
  isStreamActive: boolean;
  isStreamCompleted: boolean;
  isAwaitingUserInput: boolean;
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

const GeneralConversationRow: FC<GeneralConversationRowProps> = ({
  conversation,
  isActive,
  isOperating,
  isEditing,
  isSelected,
  inSelectionMode,
  isBulkDeleting,
  isTitlePending,
  isStreamActive,
  isStreamCompleted,
  isAwaitingUserInput,
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
  const { moveInProgress } = useConversationDragContext();
  const canEdit = conversation.can_edit !== false;
  const dragDisabled = moveInProgress || inSelectionMode || isEditing || isOperating || isBulkDeleting || !canEdit;

  const { attributes, listeners, setNodeRef: setDragNodeRef, isDragging } = useDraggable({
    id: conversation.id,
    data: { type: 'conversation', conversationId: conversation.id, fromProjectId: null },
    disabled: dragDisabled,
  });

  const { setNodeRef: setDropNodeRef, isOver } = useDroppable({
    id: `general-drop-${conversation.id}`,
    data: { projectId: null },
  });

  const assignRef = useCallback(
    (node: HTMLElement | null) => {
      setDragNodeRef(node);
      setDropNodeRef(node);
    },
    [setDragNodeRef, setDropNodeRef],
  );

  const draggableProps = dragDisabled ? {} : { ...listeners, ...attributes };
  const relativeTime = formatRelativeCompact(conversation.last_message_at || conversation.updated_at);
  const displayTitle = resolveConversationDisplayTitle(conversation);
  const hasHoverMenu = !inSelectionMode && canEdit;
  const hasTimestampMeta = !inSelectionMode && !!relativeTime && !isTitlePending && !isStreamActive && !isAwaitingUserInput;
  const reserveRightMetaSpace = hasHoverMenu || hasTimestampMeta;

  return (
    <SidebarMenuItem
      className={cn(
        "group/menu-item relative",
        isDragging && "opacity-50",
        isOver && "bg-sidebar-accent/5",
      )}
    >
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
            !canEdit && "opacity-50",
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
      <div ref={assignRef} className="flex-1" {...draggableProps}>
        <SidebarMenuButton
          isActive={isActive}
          tooltip={!inSelectionMode && !isEditing ? displayTitle : undefined}
          onClick={onRowClick}
          aria-pressed={inSelectionMode ? isSelected : undefined}
          className={cn(
            "h-[31px] py-[7px] !px-2 !rounded-[5.7px] data-[active=true]:font-normal border border-transparent active:scale-[0.98] data-[active=true]:bg-sidebar-accent transition-colors duration-200 ease-out",
            isNewlyCreated && "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-200 motion-safe:ease-out bg-accent-yellow/20 dark:bg-accent-yellow/15 border-accent-yellow/50",
            inSelectionMode ? "pl-10" : "",
            inSelectionMode && isSelected
              ? "border-sidebar-accent/60 bg-sidebar-accent/15 dark:bg-sidebar-accent/20"
              : undefined,
            reserveRightMetaSpace && "!pr-10",
          )}
        >
          <div className="flex w-full items-center gap-1.5 overflow-hidden min-w-0">
            {/* Status indicator gutter — fixed-width so every title aligns */}
            <span className="shrink-0 w-3.5 inline-flex items-center justify-center">
              {/* Default indicators — hidden on hover to reveal pin action */}
              <span className={cn("inline-flex items-center justify-center", !inSelectionMode && "group-hover/menu-item:hidden")}>
                {(isTitlePending || isStreamActive) ? (
                  <SpinnerGap className="size-3.5 animate-spin text-sidebar-foreground/30" aria-hidden="true" />
                ) : isAwaitingUserInput ? (
                  <User className="size-3.5 text-emerald-600" aria-label="Waiting for your input" />
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
      {hasTimestampMeta && (
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 type-nav-meta tabular-nums text-sidebar-foreground/30 pointer-events-none transition-opacity duration-150 group-hover/menu-item:opacity-0 group-focus-within/menu-item:opacity-0 group-has-data-[state=open]/menu-item:opacity-0 group-data-[collapsible=icon]:hidden">
          {relativeTime}
        </span>
      )}
      {hasHoverMenu && (
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

export const BackendConversations: FC<{ searchQuery?: string }> = ({ searchQuery = "" }) => {
  // ALL HOOKS MUST BE CALLED FIRST, BEFORE ANY CONDITIONAL LOGIC
  const { conversations, isLoading, error, refreshConversations, updateConversations } = useConversations();
  const navigate = useNavigate();
  const pathname = useLocation().pathname;
  const { addToast } = useToast();
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  // Track conversations with active streams and recently completed - from shared context
  const { activeStreamIds, completedStreamIds, clearCompleted, markLocalComplete } = useActiveStreams();

  // Clear the blue "completed" dot when user navigates to that conversation
  const activeConversationId = pathname.startsWith("/chat/") ? pathname.split("/chat/")[1]?.split("/")[0] : null;
  useEffect(() => {
    if (activeConversationId && completedStreamIds.has(activeConversationId)) {
      clearCompleted(activeConversationId);
    }
  }, [activeConversationId, completedStreamIds, clearCompleted]);

  // Section collapse state - start with empty to avoid hydration mismatch
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set<string>());
  const [hasHydratedSections, setHasHydratedSections] = useState(false);
  const [recentlyCreatedIds, setRecentlyCreatedIds] = useState<Set<string>>(new Set<string>());
  const recentCreateTimersRef = useRef<Map<string, number>>(new Map());

  // Load collapsed sections from localStorage after mount
  useEffect(() => {
    if (typeof window !== "undefined" && !hasHydratedSections) {
      try {
        const raw = window.localStorage.getItem("assist_sidebar_collapsed_conversation_sections");
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

  useEffect(() => {
    const timers = recentCreateTimersRef.current;
    const onConversationCreated = (event: Event) => {
      const detail = (event as CustomEvent<{ conversation?: { id?: string; project_id?: string | null } }>).detail;
      const conversation = detail?.conversation;
      const conversationId = conversation?.id;
      if (!conversationId || conversation?.project_id) return;

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
    };

    window.addEventListener("frontend:conversationCreated", onConversationCreated as EventListener);
    return () => {
      window.removeEventListener("frontend:conversationCreated", onConversationCreated as EventListener);
      timers.forEach((timeoutId) => window.clearTimeout(timeoutId));
      timers.clear();
    };
  }, []);

  const toggleSection = useCallback((sectionKey: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionKey)) {
        next.delete(sectionKey);
      } else {
        next.add(sectionKey);
      }
      try {
        window.localStorage.setItem("assist_sidebar_collapsed_conversation_sections", JSON.stringify([...next]));
      } catch {
        // Failed to save
      }
      return next;
    });
  }, []);

  const {
    selectionMode,
    selectedIds,
    isBulkDeleting,
    hiddenIds,
    setIsBulkDeleting,
    setHiddenIds,
    toggleSelection,
    enterSelectionMode,
    exitSelectionMode,
  } = useSelection();

  // Filter out optimistically hidden conversations, project conversations, and apply search query
  const displayedConversations = useMemo(() => {
    // Filter out hidden and project-associated conversations
    const filtered = conversations.filter(conv => !hiddenIds.has(conv.id) && !conv.project_id);

    if (!searchQuery.trim()) {
      return filtered;
    }

    const query = searchQuery.toLowerCase();
    return filtered.filter((conv) => conversationMatchesQuery(conv, query));
  }, [conversations, hiddenIds, searchQuery]);

  // Group conversations by time period
  const groupedConversations = useMemo(() => {
    const groups: {
      today: ConversationSummary[];
      yesterday: ConversationSummary[];
      this_week: ConversationSummary[];
      older: ConversationSummary[];
    } = {
      today: [],
      yesterday: [],
      this_week: [],
      older: []
    };

    displayedConversations.filter(c => !c.is_pinned).forEach(conv => {
      const category = categorizeByTime(conv.last_message_at || conv.updated_at);
      groups[category].push(conv);
    });

    return groups;
  }, [displayedConversations]);
  const pinnedConversations = useMemo(() => displayedConversations.filter(c => c.is_pinned), [displayedConversations]);
  const selectedIdsArray = useMemo(() => Array.from(selectedIds), [selectedIds]);
  const selectedCount = selectedIdsArray.length;

  const { setNodeRef: setGeneralDropRef, isOver: isGeneralOver } = useDroppable({
    id: 'general-conversations',
    data: { projectId: null },
  });

  // Keep stable refs to the latest callbacks to avoid re-subscribing listeners every render
  const refreshRef = useRef(refreshConversations);
  const updateRef = useRef(updateConversations);
  useEffect(() => { refreshRef.current = refreshConversations; updateRef.current = updateConversations; }, [refreshConversations, updateConversations]);
  const hasSelections = selectedCount > 0;

  const handleRequestDelete = useCallback((conversationId: string) => {
    enterSelectionMode('general', conversationId);
  }, [enterSelectionMode]);

  const handleBulkDelete = useCallback(async () => {
    if (!hasSelections || isBulkDeleting) return;
    const ids = selectedIdsArray;
    setIsBulkDeleting(true);
    setHiddenIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      return next;
    });

    const activePath = typeof window !== 'undefined' ? window.location.pathname : '';
    const deletingActive = ids.some((id) => activePath === `/chat/${id}`);

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
        updateRef.current((curr) => curr.filter((conv) => !successfulIds.has(conv.id)));
        refreshRef.current();
        if (deletingActive) {
          navigate('/');
        }
      }

      if (failureIds.size > 0) {
        addToast({
          type: 'error',
          title: 'Some chats not deleted',
          description: `${failureIds.size} chat${failureIds.size === 1 ? '' : 's'} could not be deleted.`,
        });
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
  }, [addToast, exitSelectionMode, hasSelections, isBulkDeleting, markLocalComplete, navigate, selectedIdsArray, updateRef, refreshRef, setIsBulkDeleting, setHiddenIds]);

  // Wire up the global delete button to trigger deletion
  useEffect(() => {
    if (selectionMode !== 'general') return;

    const handleGlobalDelete = () => {
      handleBulkDelete();
    };

    const deleteButton = document.getElementById('global-delete-button');
    if (deleteButton) {
      deleteButton.addEventListener('click', handleGlobalDelete);
      return () => deleteButton.removeEventListener('click', handleGlobalDelete);
    }
  }, [selectionMode, handleBulkDelete]);

  const handleStartRename = useCallback((conversationId: string) => {
    if (operatingId || selectionMode || isBulkDeleting) return; // Prevent starting rename during other operations
    setEditingId(conversationId);
  }, [operatingId, selectionMode, isBulkDeleting]);

  const handleCancelRename = useCallback(() => {
    setEditingId(null);
  }, []);

  const handleSaveRename = useCallback(async (conversationId: string, newTitle: string) => {
    if (operatingId || selectionMode || isBulkDeleting) return; // Prevent multiple operations
    
    // Start rename operation
    setOperatingId(conversationId);
    setEditingId(null); // Exit editing mode
    
    try {
      await renameConversation(conversationId, newTitle);
      
      // Success: refresh the conversations list and show success toast
      refreshConversations();
      
      addToast({
        type: 'success',
        title: 'Chat renamed',
        description: 'The conversation has been successfully renamed.'
      });
      
      // Clean up state after successful rename
      setOperatingId(null);

    } catch (error) {
      // Failed to rename conversation

      setOperatingId(null);
      
      // Show error toast
      addToast({
        type: 'error',
        title: 'Failed to rename chat',
        description: error instanceof Error ? error.message : 'An unexpected error occurred.'
      });
    }
  }, [operatingId, selectionMode, isBulkDeleting, refreshConversations, addToast]);

  const handleTogglePin = useCallback((conversationId: string) => {
    performPinToggle({
      conversationId,
      updateItems: updateConversations,
      apiCall: togglePinConversation,
      setOperatingId,
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

  const rateLimited = Boolean(error && (error.status === 429 || error.code === 'RATE_LIMITED'));
  const showLoading = isLoading && !rateLimited;

  // CONDITIONAL LOGIC AFTER ALL HOOKS
  if (error && !rateLimited) {
    return (
      <div className="px-2 py-2">
        <p className="type-caption text-destructive">{error.message}</p>
        {error.detail ? (
          <p className="mt-1 type-nav-meta text-sidebar-foreground/50">{error.detail}</p>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => {
            void refreshConversations();
          }}
        >
          Retry
        </Button>
      </div>
    );
  }

  if (showLoading) {
    return (
      <div className="px-2 py-1.5 space-y-1.5">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-7 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (!rateLimited && displayedConversations.length === 0) {
    return (
      <div
        ref={setGeneralDropRef}
        className={cn(
          "px-2 py-2",
          isGeneralOver && "rounded-xl border border-sidebar-accent/40 bg-sidebar-accent/10",
        )}
      >
        <p className="type-caption text-sidebar-foreground/50">
          {searchQuery.trim() ? 'No matching conversations' : 'No conversations yet'}
        </p>
        <p className="mt-1 type-nav-meta text-sidebar-foreground/30">
          Drag a chat here to move it out of a project.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={setGeneralDropRef}
      className={cn(
        isGeneralOver && "rounded-xl border border-sidebar-accent/40 bg-sidebar-accent/10",
      )}
    >
      {rateLimited ? (
        <div className="px-2 pt-2 pb-3 space-y-2">
          <div className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-50 px-3 py-2 type-caption text-amber-900 dark:border-amber-300/30 dark:bg-amber-900/20 dark:text-amber-100">
            <Warning className="mt-0.5 size-4 shrink-0" />
            <div className="space-y-1">
              <p className="type-control-compact leading-tight">Temporarily rate limited</p>
              <p className="type-nav-meta leading-snug text-amber-900/80 dark:text-amber-100/80">
                {error?.detail || `Too many requests. Try again in about ${formatRetryAfter(error?.retryAfterSeconds)}.`}
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-center"
            onClick={() => {
              void refreshConversations();
            }}
          >
            Retry now
          </Button>
        </div>
      ) : null}
      {/* Pinned */}
      {pinnedConversations.length > 0 && (
        <>
          <SectionHeader
            label="Pinned"
            isCollapsed={collapsedSections.has("pinned")}
            onToggle={() => toggleSection("pinned")}
          />
          {!collapsedSections.has("pinned") && pinnedConversations.map((conversation) => {
            const isActive = pathname === `/chat/${conversation.id}`;
            const isSelected = selectedIds.has(conversation.id);
            const inGeneralSelectionMode = selectionMode === 'general';
            const canEdit = conversation.can_edit !== false;
            const handleRowClick = inGeneralSelectionMode
              ? (canEdit ? () => toggleSelection(conversation.id) : undefined)
              : editingId === conversation.id
                ? undefined
                : () => navigate(`/chat/${conversation.id}`);
            const isOperating = operatingId === conversation.id;
            const isEditing = editingId === conversation.id;
            const isStreamActive = activeStreamIds.has(conversation.id);
            const isStreamCompleted = completedStreamIds.has(conversation.id);
            const isAwaitingUserInput = Boolean(conversation.awaiting_user_input) && !isStreamActive;

            return (
              <GeneralConversationRow
                key={conversation.id}
                conversation={conversation}
                isActive={isActive}
                isOperating={isOperating}
                isEditing={isEditing}
                isSelected={isSelected}
                inSelectionMode={inGeneralSelectionMode}
                isBulkDeleting={isBulkDeleting}
                isTitlePending={false}
                isStreamActive={isStreamActive}
                isStreamCompleted={isStreamCompleted}
                isAwaitingUserInput={isAwaitingUserInput}
                isNewlyCreated={recentlyCreatedIds.has(conversation.id)}
                onRowClick={handleRowClick}
                onToggleSelection={() => toggleSelection(conversation.id)}
                onStartRename={() => handleStartRename(conversation.id)}
                onSaveRename={(newTitle) => handleSaveRename(conversation.id, newTitle)}
                onCancelRename={handleCancelRename}
                onRequestDelete={() => handleRequestDelete(conversation.id)}
                onTogglePin={() => handleTogglePin(conversation.id)}
                onGoToParent={buildGoToParent(conversation)}
              />
            );
          })}
        </>
      )}

      {/* Today */}
      {groupedConversations.today.length > 0 && (
        <>
          <SectionHeader
            label="Today"
            isCollapsed={collapsedSections.has("today")}
            onToggle={() => toggleSection("today")}
          />
          {!collapsedSections.has("today") && groupedConversations.today.map((conversation) => {
            const isActive = pathname === `/chat/${conversation.id}`;
            const isSelected = selectedIds.has(conversation.id);
            const inGeneralSelectionMode = selectionMode === 'general';
            const canEdit = conversation.can_edit !== false;
            const handleRowClick = inGeneralSelectionMode
              ? (canEdit ? () => toggleSelection(conversation.id) : undefined)
              : editingId === conversation.id
                ? undefined
                : () => navigate(`/chat/${conversation.id}`);
            const isOperating = operatingId === conversation.id;
            const isEditing = editingId === conversation.id;
            const isStreamActive = activeStreamIds.has(conversation.id);
            const isStreamCompleted = completedStreamIds.has(conversation.id);
            const isAwaitingUserInput = Boolean(conversation.awaiting_user_input) && !isStreamActive;

            return (
              <GeneralConversationRow
                key={conversation.id}
                conversation={conversation}
                isActive={isActive}
                isOperating={isOperating}
                isEditing={isEditing}
                isSelected={isSelected}
                inSelectionMode={inGeneralSelectionMode}
                isBulkDeleting={isBulkDeleting}
                isTitlePending={false}
                isStreamActive={isStreamActive}
                isStreamCompleted={isStreamCompleted}
                isAwaitingUserInput={isAwaitingUserInput}
                isNewlyCreated={recentlyCreatedIds.has(conversation.id)}
                onRowClick={handleRowClick}
                onToggleSelection={() => toggleSelection(conversation.id)}
                onStartRename={() => handleStartRename(conversation.id)}
                onSaveRename={(newTitle) => handleSaveRename(conversation.id, newTitle)}
                onCancelRename={handleCancelRename}
                onRequestDelete={() => handleRequestDelete(conversation.id)}
                onTogglePin={() => handleTogglePin(conversation.id)}
                onGoToParent={buildGoToParent(conversation)}
              />
            );
          })}
        </>
      )}

      {/* Yesterday */}
      {groupedConversations.yesterday.length > 0 && (
        <>
          <SectionHeader
            label="Yesterday"
            isCollapsed={collapsedSections.has("yesterday")}
            onToggle={() => toggleSection("yesterday")}
          />
          {!collapsedSections.has("yesterday") && groupedConversations.yesterday.map((conversation) => {
            const isActive = pathname === `/chat/${conversation.id}`;
            const isSelected = selectedIds.has(conversation.id);
            const inGeneralSelectionMode = selectionMode === 'general';
            const canEdit = conversation.can_edit !== false;
            const handleRowClick = inGeneralSelectionMode
              ? (canEdit ? () => toggleSelection(conversation.id) : undefined)
              : editingId === conversation.id
                ? undefined
                : () => navigate(`/chat/${conversation.id}`);
            const isOperating = operatingId === conversation.id;
            const isEditing = editingId === conversation.id;
            const isStreamActive = activeStreamIds.has(conversation.id);
            const isStreamCompleted = completedStreamIds.has(conversation.id);
            const isAwaitingUserInput = Boolean(conversation.awaiting_user_input) && !isStreamActive;

            return (
              <GeneralConversationRow
                key={conversation.id}
                conversation={conversation}
                isActive={isActive}
                isOperating={isOperating}
                isEditing={isEditing}
                isSelected={isSelected}
                inSelectionMode={inGeneralSelectionMode}
                isBulkDeleting={isBulkDeleting}
                isTitlePending={false}
                isStreamActive={isStreamActive}
                isStreamCompleted={isStreamCompleted}
                isAwaitingUserInput={isAwaitingUserInput}
                isNewlyCreated={recentlyCreatedIds.has(conversation.id)}
                onRowClick={handleRowClick}
                onToggleSelection={() => toggleSelection(conversation.id)}
                onStartRename={() => handleStartRename(conversation.id)}
                onSaveRename={(newTitle) => handleSaveRename(conversation.id, newTitle)}
                onCancelRename={handleCancelRename}
                onRequestDelete={() => handleRequestDelete(conversation.id)}
                onTogglePin={() => handleTogglePin(conversation.id)}
                onGoToParent={buildGoToParent(conversation)}
              />
            );
          })}
        </>
      )}

      {/* This Week */}
      {groupedConversations.this_week.length > 0 && (
        <>
          <SectionHeader
            label="This Week"
            isCollapsed={collapsedSections.has("this_week")}
            onToggle={() => toggleSection("this_week")}
          />
          {!collapsedSections.has("this_week") && groupedConversations.this_week.map((conversation) => {
            const isActive = pathname === `/chat/${conversation.id}`;
            const isSelected = selectedIds.has(conversation.id);
            const inGeneralSelectionMode = selectionMode === 'general';
            const canEdit = conversation.can_edit !== false;
            const handleRowClick = inGeneralSelectionMode
              ? (canEdit ? () => toggleSelection(conversation.id) : undefined)
              : editingId === conversation.id
                ? undefined
                : () => navigate(`/chat/${conversation.id}`);
            const isOperating = operatingId === conversation.id;
            const isEditing = editingId === conversation.id;
            const isStreamActive = activeStreamIds.has(conversation.id);
            const isStreamCompleted = completedStreamIds.has(conversation.id);
            const isAwaitingUserInput = Boolean(conversation.awaiting_user_input) && !isStreamActive;

            return (
              <GeneralConversationRow
                key={conversation.id}
                conversation={conversation}
                isActive={isActive}
                isOperating={isOperating}
                isEditing={isEditing}
                isSelected={isSelected}
                inSelectionMode={inGeneralSelectionMode}
                isBulkDeleting={isBulkDeleting}
                isTitlePending={false}
                isStreamActive={isStreamActive}
                isStreamCompleted={isStreamCompleted}
                isAwaitingUserInput={isAwaitingUserInput}
                isNewlyCreated={recentlyCreatedIds.has(conversation.id)}
                onRowClick={handleRowClick}
                onToggleSelection={() => toggleSelection(conversation.id)}
                onStartRename={() => handleStartRename(conversation.id)}
                onSaveRename={(newTitle) => handleSaveRename(conversation.id, newTitle)}
                onCancelRename={handleCancelRename}
                onRequestDelete={() => handleRequestDelete(conversation.id)}
                onTogglePin={() => handleTogglePin(conversation.id)}
                onGoToParent={buildGoToParent(conversation)}
              />
            );
          })}
        </>
      )}

      {/* Older */}
      {groupedConversations.older.length > 0 && (
        <>
          <SectionHeader
            label="Older"
            isCollapsed={collapsedSections.has("older")}
            onToggle={() => toggleSection("older")}
          />
          {!collapsedSections.has("older") && groupedConversations.older.map((conversation) => {
            const isActive = pathname === `/chat/${conversation.id}`;
            const isSelected = selectedIds.has(conversation.id);
            const inGeneralSelectionMode = selectionMode === 'general';
            const canEdit = conversation.can_edit !== false;
            const handleRowClick = inGeneralSelectionMode
              ? (canEdit ? () => toggleSelection(conversation.id) : undefined)
              : editingId === conversation.id
                ? undefined
                : () => navigate(`/chat/${conversation.id}`);
            const isOperating = operatingId === conversation.id;
            const isEditing = editingId === conversation.id;
            const isStreamActive = activeStreamIds.has(conversation.id);
            const isStreamCompleted = completedStreamIds.has(conversation.id);
            const isAwaitingUserInput = Boolean(conversation.awaiting_user_input) && !isStreamActive;

            return (
              <GeneralConversationRow
                key={conversation.id}
                conversation={conversation}
                isActive={isActive}
                isOperating={isOperating}
                isEditing={isEditing}
                isSelected={isSelected}
                inSelectionMode={inGeneralSelectionMode}
                isBulkDeleting={isBulkDeleting}
                isTitlePending={false}
                isStreamActive={isStreamActive}
                isStreamCompleted={isStreamCompleted}
                isAwaitingUserInput={isAwaitingUserInput}
                isNewlyCreated={recentlyCreatedIds.has(conversation.id)}
                onRowClick={handleRowClick}
                onToggleSelection={() => toggleSelection(conversation.id)}
                onStartRename={() => handleStartRename(conversation.id)}
                onSaveRename={(newTitle) => handleSaveRename(conversation.id, newTitle)}
                onCancelRename={handleCancelRename}
                onRequestDelete={() => handleRequestDelete(conversation.id)}
                onTogglePin={() => handleTogglePin(conversation.id)}
                onGoToParent={buildGoToParent(conversation)}
              />
            );
          })}
        </>
      )}
    </div>
  );
};
