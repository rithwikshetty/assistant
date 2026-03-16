
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useEffect,
  useState,
  type PropsWithChildren,
} from "react";

export type InsightSidebarPayload = {
  message: unknown;
  messageId: string | null;
  sourceCount: number;
};

type InsightSidebarContextValue = {
  isOpen: boolean;
  data: InsightSidebarPayload | null;
  openSidebar: (payload: InsightSidebarPayload) => void;
  updateSidebar: (payload: InsightSidebarPayload) => void;
  closeSidebar: () => void;
};

const InsightSidebarContext = createContext<InsightSidebarContextValue | null>(null);

export const InsightSidebarProvider = ({ children }: PropsWithChildren) => {
  const [isOpen, setIsOpen] = useState(false);
  const [data, setData] = useState<InsightSidebarPayload | null>(null);

  const openSidebar = useCallback((payload: InsightSidebarPayload) => {
    setData(payload);
    setIsOpen(true);
  }, []);

  const updateSidebar = useCallback((payload: InsightSidebarPayload) => {
    setData((current) => {
      if (!current) return payload;
      if (current.messageId !== payload.messageId) return current;
      return payload;
    });
  }, []);

  const closeSidebar = useCallback(() => {
    setIsOpen(false);
  }, []);

  // Allow closing the sidebar with Escape when open.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        try { e.stopPropagation(); } catch {}
        setIsOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen]);

  const value = useMemo<InsightSidebarContextValue>(
    () => ({
      isOpen,
      data,
      openSidebar,
      updateSidebar,
      closeSidebar,
    }),
    [closeSidebar, data, isOpen, openSidebar, updateSidebar],
  );

  return <InsightSidebarContext.Provider value={value}>{children}</InsightSidebarContext.Provider>;
};

export const useInsightSidebar = () => {
  const ctx = useContext(InsightSidebarContext);
  if (!ctx) {
    throw new Error("useInsightSidebar must be used within an InsightSidebarProvider");
  }
  return ctx;
};

export const useOptionalInsightSidebar = () => useContext(InsightSidebarContext);
