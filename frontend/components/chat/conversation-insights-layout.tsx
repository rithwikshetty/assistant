import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useInsightSidebar } from "@/components/chat/insights/insight-sidebar-context";
import { MessageInsightsSidebar } from "@/components/chat/message-insights-sidebar";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type ConversationInsightsLayoutProps = {
  conversationId: string;
  onInsightsOpenChange?: (open: boolean) => void;
  header: ReactNode;
  children: ReactNode;
};

export const ConversationInsightsLayout = ({
  conversationId,
  onInsightsOpenChange,
  header,
  children,
}: ConversationInsightsLayoutProps) => {
  const { isOpen, data, closeSidebar } = useInsightSidebar();
  const insightsHeadingId = "insights-heading";

  useEffect(() => {
    closeSidebar();
  }, [conversationId, closeSidebar]);

  useEffect(() => {
    onInsightsOpenChange?.(isOpen);
  }, [isOpen, onInsightsOpenChange]);

  const sidebarContent = (
    <>
      {/* Desktop fixed right sidebar — rendered via portal to escape stacking contexts */}
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-30 hidden w-[22rem] border-l border-border/60 bg-background md:flex",
          "transition-[transform,opacity] duration-200 ease-md-standard",
          isOpen ? "translate-x-0 opacity-100" : "translate-x-full opacity-0 pointer-events-none",
        )}
      >
        <MessageInsightsSidebar
          open={isOpen}
          payload={data}
          onClose={closeSidebar}
          headingId={insightsHeadingId}
          className="flex h-full min-h-0 w-full flex-col"
        />
      </aside>

      {/* Mobile overlay */}
      {isOpen ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="absolute inset-0 bg-background/70 backdrop-blur-sm" aria-hidden onClick={closeSidebar} />
          <div
            className="relative z-10 ml-auto flex h-full min-h-0 w-full max-w-xs flex-col overflow-hidden border-l border-border/60 bg-background"
            role="dialog"
            aria-modal="true"
            aria-labelledby={insightsHeadingId}
          >
            <MessageInsightsSidebar
              open
              payload={data}
              onClose={closeSidebar}
              headingId={insightsHeadingId}
              className="flex h-full min-h-0 w-full flex-col"
            />
          </div>
        </div>
      ) : null}
    </>
  );

  return (
    <div className="flex h-full min-h-0 w-full overflow-hidden">
      {/* Main column (chat) */}
      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {header}
        <div className="relative flex-1 min-h-0 overflow-hidden">{children}</div>
      </div>

      {/* Right gap to reserve space for the fixed sidebar on desktop */}
      <div
        aria-hidden
        className={cn(
          "hidden h-full min-h-0 md:block transition-[width] duration-200 ease-md-standard pointer-events-none",
          isOpen ? "w-[22rem]" : "w-0",
        )}
      />

      {/* Portal the sidebar to document.body to escape any parent stacking contexts */}
      {typeof document !== "undefined" ? createPortal(sidebarContent, document.body) : null}
    </div>
  );
};
