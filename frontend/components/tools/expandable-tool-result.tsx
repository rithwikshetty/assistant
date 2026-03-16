
import { useCallback, useEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, CSSProperties, MouseEvent, ReactNode } from "react";
import { CaretRight } from "@phosphor-icons/react";
import type { Icon as IconComponent } from "@phosphor-icons/react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { createContext, useContext } from "react";

// Auto-scroll context - can be provided by ThreadLayout or a simpler provider
type AutoScrollControl = {
  lockAutoScroll: () => () => void;
};

const defaultAutoScrollControl: AutoScrollControl = {
  lockAutoScroll: () => () => {},
};

export const ExpandableToolAutoScrollContext = createContext<AutoScrollControl>(defaultAutoScrollControl);

// Use the context if provided, otherwise use default no-op
const useAutoScrollControl = () => {
  return useContext(ExpandableToolAutoScrollContext);
};

const shimmerStyle: CSSProperties = {
  background: "linear-gradient(90deg, currentColor 0%, rgba(255, 255, 255, 0.3) 25%, currentColor 50%, currentColor 100%)",
  backgroundSize: "200% 100%",
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  animation: "shimmer 2s linear infinite",
};

interface ExpandableToolResultProps {
  icon: IconComponent;
  isLoading: boolean;
  isComplete: boolean;
  count: number;
  loadingLabel: string;
  completeLabel: (count: number) => ReactNode;
  emptyLabel: string;
  error?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  renderToggleIcon?: (expanded: boolean) => ReactNode;
  buttonProps?: ButtonHTMLAttributes<HTMLButtonElement>;
  /**
   * When true and there are no results, suppress the outer empty banner and
   * allow the caller to render an inline empty state inside the expandable area.
   */
  showEmptyInside?: boolean;
  /**
   * When true, auto-expand once when results arrive after loading.
   * Useful for admin-y tools where immediate visibility is preferred.
   */
  autoExpandOnComplete?: boolean;
  /**
   * Optional class applied to the icon when in the complete (non-loading) state.
   * Use for per-tool accent colors (e.g. "text-orange-600 dark:text-orange-400").
   */
  completeIconClassName?: string;
}

/**
 * Shared expandable status block for streamed tool calls.
 */
export function ExpandableToolResult({
  icon: Icon,
  isLoading,
  isComplete,
  count,
  loadingLabel,
  completeLabel,
  emptyLabel,
  error,
  children,
  className,
  contentClassName,
  renderToggleIcon,
  buttonProps,
  showEmptyInside = false,
  autoExpandOnComplete = false,
  completeIconClassName,
}: ExpandableToolResultProps) {
  const [expanded, setExpanded] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const showLoading = isLoading;
  const hasResults = count > 0;
  const { onClick: externalOnClick, ...restButtonProps } = buttonProps ?? {};
  const { lockAutoScroll } = useAutoScrollControl();
  const releaseAutoScrollRef = useRef<(() => void) | null>(null);

  const releaseAutoScrollLock = useCallback(() => {
    if (releaseAutoScrollRef.current) {
      releaseAutoScrollRef.current();
      releaseAutoScrollRef.current = null;
    }
  }, []);

  const getViewportElement = useCallback(() => {
    const root = rootRef.current;
    if (!root) return null;
    const viewport = root.closest<HTMLElement>("[data-thread-viewport]");
    return viewport;
  }, []);

  const preventViewportAutoScroll = useCallback(() => {
    const viewport = getViewportElement();
    if (!viewport) return;

    const { scrollTop, scrollHeight, clientHeight } = viewport;
    const distanceFromBottom = scrollHeight - clientHeight - scrollTop;

    if (distanceFromBottom <= 1) {
      const targetScrollTop = Math.max(0, scrollHeight - clientHeight - 1);
      viewport.scrollTop = targetScrollTop;
    }
  }, [getViewportElement]);

  const handleToggleClick = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      externalOnClick?.(event);
      if (event.defaultPrevented) {
        return;
      }

      setExpanded((prev) => {
        const next = !prev;
        if (!prev && next && !showLoading) {
          preventViewportAutoScroll();
        }
        return next;
      });
    },
    [externalOnClick, preventViewportAutoScroll, showLoading],
  );

  const toggleIcon = renderToggleIcon
    ? renderToggleIcon(expanded)
    : (
      <motion.span
        animate={{ rotate: expanded ? 90 : 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 20 }}
        className="inline-flex"
      >
        <CaretRight className="w-4 h-4" weight="bold" />
      </motion.span>
    );

  useEffect(() => {
    if (!showLoading) {
      return;
    }
    setExpanded((prev) => (prev ? false : prev));
  }, [showLoading]);

  // Never auto-open; expansion is always user-controlled.
  const autoOpenedRef = useRef(false);
  useEffect(() => {
    if (!showLoading && autoExpandOnComplete && !expanded && !autoOpenedRef.current) {
      autoOpenedRef.current = true;
      setExpanded(true);
    }
  }, [showLoading, autoExpandOnComplete, expanded]);

  useEffect(() => {
    if (!showLoading && expanded) {
      if (!releaseAutoScrollRef.current) {
        releaseAutoScrollRef.current = lockAutoScroll();
      }
    } else {
      releaseAutoScrollLock();
    }
  }, [lockAutoScroll, expanded, releaseAutoScrollLock, showLoading]);

  useEffect(() => {
    return () => {
      releaseAutoScrollLock();
    };
  }, [releaseAutoScrollLock]);

  return (
    <div ref={rootRef} className={cn("space-y-2", className)}>
      {(showLoading || isComplete) && (
        <div className="type-size-14 text-muted-foreground">
          {showLoading ? (
            <div className="flex items-center gap-2 max-w-full">
              <span className="tool-rail-anchor relative inline-flex flex-shrink-0">
                <Icon className="w-4 h-4" />
              </span>
              <span className="font-medium relative inline-block truncate max-w-[500px]" style={shimmerStyle}>
                {loadingLabel}
              </span>
            </div>
          ) : (
            <button
              type="button"
              onClick={handleToggleClick}
              className="inline-flex max-w-full items-center gap-2 border-0 bg-transparent p-0 type-size-14 text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground"
              aria-expanded={expanded}
              {...restButtonProps}
            >
              <span className={cn("tool-rail-anchor relative inline-flex flex-shrink-0", completeIconClassName)}>
                <Icon className="w-4 h-4" />
              </span>
              <span className="type-size-14 font-medium truncate max-w-[500px]">{completeLabel(count)}</span>
              <span className="flex-shrink-0">{toggleIcon}</span>
            </button>
          )}
        </div>
      )}

      {!showLoading && !error && !hasResults && !showEmptyInside && (
        <div className="rounded-lg border border-muted bg-muted/50 p-3 type-size-14 text-muted-foreground text-center">
          {emptyLabel}
        </div>
      )}

      <AnimatePresence initial={false}>
        {!showLoading && expanded && (hasResults || showEmptyInside || error) ? (
          <motion.div
            key="tool-content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            style={{ overflow: "hidden" }}
            className="will-change-[height,opacity]"
          >
            <div
              className={cn(
                "rounded-lg border border-border/40 bg-card p-4 dark:border-border/30",
                error && "border-destructive/40",
                contentClassName,
              )}
            >
              {error ? (
                <p className="type-size-14 text-destructive">{error}</p>
              ) : (
                children
              )}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
