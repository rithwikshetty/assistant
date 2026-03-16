
import { createContext, useContext, useState, useCallback, ReactNode, FC, useEffect } from "react";

interface SelectionContextType {
  selectionMode: 'general' | 'project' | null;
  selectedProjectId: string | null;
  selectedIds: Set<string>;
  isBulkDeleting: boolean;
  hiddenIds: Set<string>;
  setSelectionMode: (mode: 'general' | 'project' | null) => void;
  setSelectedProjectId: (projectId: string | null) => void;
  setSelectedIds: (ids: Set<string> | ((prev: Set<string>) => Set<string>)) => void;
  setIsBulkDeleting: (deleting: boolean) => void;
  setHiddenIds: (ids: Set<string> | ((prev: Set<string>) => Set<string>)) => void;
  toggleSelection: (id: string) => void;
  enterSelectionMode: (mode: 'general' | 'project', conversationId: string, projectId?: string) => void;
  exitSelectionMode: () => void;
}

const SelectionContext = createContext<SelectionContextType | undefined>(undefined);

export const SelectionProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const [selectionMode, setSelectionMode] = useState<'general' | 'project' | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());

  const toggleSelection = useCallback((conversationId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(conversationId)) {
        next.delete(conversationId);
      } else {
        next.add(conversationId);
      }
      return next;
    });
  }, []);

  const enterSelectionMode = useCallback((mode: 'general' | 'project', conversationId: string, projectId?: string) => {
    if (isBulkDeleting) return;
    setSelectionMode(mode);
    setSelectedProjectId(projectId || null);
    setSelectedIds(new Set([conversationId]));
  }, [isBulkDeleting]);

  const exitSelectionMode = useCallback(() => {
    if (isBulkDeleting) return;
    setSelectionMode(null);
    setSelectedProjectId(null);
    setSelectedIds(new Set());
  }, [isBulkDeleting]);

  // Exit selection mode on Escape key
  useEffect(() => {
    if (!selectionMode) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        exitSelectionMode();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectionMode, exitSelectionMode]);

  // Auto-exit selection mode if all selections are cleared
  useEffect(() => {
    if (!selectionMode || isBulkDeleting) return;
    if (selectedIds.size === 0) {
      exitSelectionMode();
    }
  }, [selectionMode, isBulkDeleting, selectedIds.size, exitSelectionMode]);

  return (
    <SelectionContext.Provider
      value={{
        selectionMode,
        selectedProjectId,
        selectedIds,
        isBulkDeleting,
        hiddenIds,
        setSelectionMode,
        setSelectedProjectId,
        setSelectedIds,
        setIsBulkDeleting,
        setHiddenIds,
        toggleSelection,
        enterSelectionMode,
        exitSelectionMode,
      }}
    >
      {children}
    </SelectionContext.Provider>
  );
};

export const useSelection = () => {
  const context = useContext(SelectionContext);
  if (!context) {
    throw new Error("useSelection must be used within a SelectionProvider");
  }
  return context;
};
