import { useCallback, useState, type FC } from "react";
import { useNavigate } from "react-router-dom";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Plus, X, Trash, SpinnerGap } from "@phosphor-icons/react";
import { BackendConversations } from "./backend-conversations";
import { ProjectList } from "./project-list";
import { SelectionProvider, useSelection } from "@/contexts/selection-context";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  DndContext,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { ConversationDragContextProvider, type ActiveDrag } from "./conversation-dnd-context";
import { useConversations } from "@/hooks/use-conversations";
import { useProjects } from "@/hooks/use-projects";
import { conversationResponseToSummary, updateConversationProject } from "@/lib/api/auth";
import { useToast } from "@/components/ui/toast";
import { resolveConversationDisplayTitle } from "@/lib/conversation-titles";

type DragItemData = {
  type: 'conversation';
  conversationId: string;
  fromProjectId: string | null;
};

type DropZoneData = {
  projectId: string | null;
};

const SelectionToolbar: FC = () => {
  const { selectionMode, selectedIds, isBulkDeleting, exitSelectionMode } = useSelection();

  if (!selectionMode) return null;

  const selectedCount = selectedIds.size;

  return (
    <div className="sticky top-0 z-20 bg-sidebar px-2 pb-2 transition-all duration-200">
      <div className="flex items-center gap-2 type-control-compact text-sidebar-foreground">
        <span className="sr-only" aria-live="polite">
          {selectedCount === 1 ? '1 chat selected' : `${selectedCount} chats selected`}
        </span>
        <div className="flex w-full items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={exitSelectionMode}
            disabled={isBulkDeleting}
            className="flex-[3] justify-start"
          >
            <X className="mr-2 size-4" />
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={selectedCount === 0 || isBulkDeleting}
            className="flex-[7] justify-center"
            id="global-delete-button"
          >
            {isBulkDeleting ? (
              <>
                <SpinnerGap className="mr-2 size-4 animate-spin" />
                Deleting…
              </>
            ) : (
              <>
                <Trash className="mr-2 size-4" />
                {selectedCount > 0 ? `Delete (${selectedCount})` : 'Delete'}
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
};

export const ThreadListContent: FC<{ searchQuery?: string }> = ({ searchQuery = "" }) => {
  const { conversations, updateConversations } = useConversations();
  const { projects, updateProjects } = useProjects();
  const { addToast } = useToast();

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 120, tolerance: 8 } }),
  );

  const [activeDrag, setActiveDrag] = useState<ActiveDrag | null>(null);
  const [moveInProgress, setMoveInProgress] = useState(false);

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      if (moveInProgress) return;
      const data = event.active.data.current as DragItemData | undefined;
      if (!data) return;

      if (data.type === 'conversation') {
        setActiveDrag({
          type: 'conversation',
          conversationId: data.conversationId,
          fromProjectId: data.fromProjectId ?? null,
        });
      }
    },
    [moveInProgress],
  );

  const handleDragCancel = useCallback(() => {
    setActiveDrag(null);
  }, []);

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const dragData = event.active.data.current as DragItemData | undefined;
      const overData = event.over?.data.current as DropZoneData | undefined;

      setActiveDrag(null);

      if (!dragData) {
        return;
      }
      if (dragData.type === 'conversation') {
        if (moveInProgress) {
          return;
        }

        const destinationProjectId = overData?.projectId ?? null;

        if (!event.over || destinationProjectId === dragData.fromProjectId) {
          return;
        }

        setMoveInProgress(true);
        try {
          const updated = await updateConversationProject(dragData.conversationId, destinationProjectId);
          const summary = conversationResponseToSummary(updated);

          updateConversations((current) => {
            const idx = current.findIndex((conv) => conv.id === summary.id);
            if (idx === -1) {
              return [summary, ...current];
            }
            const next = current.slice();
            next[idx] = { ...next[idx], ...summary };
            return next;
          });

          updateProjects((current) => {
            let changed = false;
            const timestamp = new Date().toISOString();
            const mapped = current.map((projectItem) => {
              if (projectItem.id === dragData.fromProjectId) {
                changed = true;
                return {
                  ...projectItem,
                  conversation_count: Math.max((projectItem.conversation_count ?? 1) - 1, 0),
                  updated_at: timestamp,
                };
              }
              if (projectItem.id === destinationProjectId) {
                changed = true;
                return {
                  ...projectItem,
                  conversation_count: (projectItem.conversation_count ?? 0) + 1,
                  updated_at: timestamp,
                };
              }
              return projectItem;
            });
            return changed ? mapped : current;
          });

          if (destinationProjectId) {
            window.dispatchEvent(
              new CustomEvent('frontend:conversationMoved', {
                detail: { projectId: destinationProjectId, conversationId: summary.id },
              }),
            );
          }

          const destinationLabel = destinationProjectId
            ? projects.find((projectItem) => projectItem.id === destinationProjectId)?.name ?? 'project'
            : 'general chats';

          addToast({
            type: 'success',
            title: 'Chat moved',
            description: destinationProjectId
              ? `Conversation moved to ${destinationLabel}.`
              : 'Conversation moved back to general chats.',
          });
        } catch (error) {
          // Failed to update conversation project
          addToast({
            type: 'error',
            title: "Couldn't move chat",
            description: error instanceof Error ? error.message : 'Please try again.',
          });
        } finally {
          setMoveInProgress(false);
        }
        return;
      }
    },
    [addToast, moveInProgress, projects, updateConversations, updateProjects],
  );

  return (
    <SelectionProvider>
      <ConversationDragContextProvider value={{ activeDrag, moveInProgress }}>
        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={handleDragCancel}
        >
          <SidebarMenu className="px-1.5 py-1">
            <SelectionToolbar />
            <ProjectList searchQuery={searchQuery} />
            <BackendConversations searchQuery={searchQuery} />
          </SidebarMenu>
          <DragOverlay>
            {activeDrag && activeDrag.type === 'conversation' ? (() => {
              const conversation = conversations.find(c => c.id === activeDrag.conversationId);
              return (
                <div className="h-8 px-3 py-1.5 bg-sidebar-accent rounded-md shadow-lg border border-sidebar-border/40 opacity-90 flex items-center">
                  <span className="type-control-compact text-sidebar-foreground truncate">
                    {conversation ? resolveConversationDisplayTitle(conversation) : 'New conversation'}
                  </span>
                </div>
              );
            })() : null}
          </DragOverlay>
        </DndContext>
      </ConversationDragContextProvider>
    </SelectionProvider>
  );
};

export const ThreadListNew: FC = () => {
  const navigate = useNavigate();
  const handleNewChatClick = useCallback(() => {
    navigate("/");
  }, [navigate]);

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip="New chat"
        onClick={handleNewChatClick}
        className={cn(
          "font-medium h-8 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent",
        )}
      >
        <Plus className="size-4 shrink-0" />
        <span>New chat</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
};
