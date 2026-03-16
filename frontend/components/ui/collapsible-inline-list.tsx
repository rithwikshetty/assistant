import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CaretDown } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

type CollapsibleInlineListProps = {
  /** Icon rendered at the start of the header */
  icon: ReactNode;
  /** Label text in the header */
  label: string;
  /** Extra elements after the label (badges, counts) */
  headerExtra?: ReactNode;
  /** Elements on the right side of the header, before the chevron */
  headerActions?: ReactNode;
  expanded: boolean;
  onToggle: () => void;
  /** Enable max-height scroll container with bottom fade gradient */
  scrollable?: boolean;
  /** Max height of the scroll container (default "7.25rem") */
  maxHeight?: string;
  /** When true, the expanded content floats upward as an overlay so it
   *  doesn't push surrounding layout around. The collapsed header still
   *  takes normal space in the document flow. */
  overlayExpand?: boolean;
  /** When true, renders without its own border/bg/rounded wrapper.
   *  Use when the parent container (e.g. ChatInput card) provides the chrome. */
  bare?: boolean;
  children: ReactNode;
  className?: string;
};

export const CollapsibleInlineList: React.FC<CollapsibleInlineListProps> = ({
  icon,
  label,
  headerExtra,
  headerActions,
  expanded,
  onToggle,
  scrollable = false,
  maxHeight = "7.25rem",
  overlayExpand = false,
  bare = false,
  children,
  className,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLButtonElement>(null);
  const [canScrollDown, setCanScrollDown] = useState(false);
  const [headerHeight, setHeaderHeight] = useState(0);

  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) { setCanScrollDown(false); return; }
    setCanScrollDown(el.scrollHeight - el.scrollTop - el.clientHeight > 2);
  }, []);

  useEffect(() => {
    if (expanded && scrollable) {
      const t = setTimeout(checkScroll, 250);
      return () => clearTimeout(t);
    }
    setCanScrollDown(false);
  }, [expanded, scrollable, checkScroll]);

  // Measure header height for overlay mode so the spacer matches exactly
  useLayoutEffect(() => {
    if (overlayExpand && headerRef.current) {
      // header height + 2px border
      setHeaderHeight(headerRef.current.offsetHeight + 2);
    }
  }, [overlayExpand]);

  const headerButton = (
    <button
      ref={headerRef}
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between gap-2 px-3.5 py-2 type-size-12 font-medium text-foreground/70 hover:bg-muted/20 transition-colors cursor-pointer outline-none"
    >
      <div className="flex items-center gap-2 min-w-0">
        {icon}
        <span>{label}</span>
        {headerExtra}
      </div>
      <div className="flex items-center gap-2">
        {headerActions}
        <CaretDown
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform duration-200",
            expanded ? "rotate-180" : ""
          )}
        />
      </div>
    </button>
  );

  const expandedContent = (
    <AnimatePresence initial={false}>
      {expanded && (
        <motion.div
          initial={{ height: 0 }}
          animate={{ height: "auto" }}
          exit={{ height: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="overflow-clip"
        >
          <div className="relative border-t border-border/10">
            <div
              ref={scrollable ? scrollRef : undefined}
              onScroll={scrollable ? checkScroll : undefined}
              className={cn(
                "flex flex-col divide-y divide-border/5",
                scrollable && "overflow-y-auto scrollbar-thin scrollbar-thumb-border/40 scrollbar-track-transparent"
              )}
              style={scrollable ? { maxHeight } : undefined}
            >
              {children}
            </div>
            {scrollable && (
              <div
                className={cn(
                  "pointer-events-none absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-background to-transparent transition-opacity duration-200",
                  canScrollDown ? "opacity-100" : "opacity-0"
                )}
              />
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  if (bare) {
    // Bare mode: no border/bg/rounded wrapper — parent provides the chrome.
    // overlayExpand is ignored in bare mode.
    return (
      <div className={cn("w-full", className)}>
        {headerButton}
        {expandedContent}
      </div>
    );
  }

  if (overlayExpand) {
    // Fixed-height wrapper keeps the header in flow; the full card is
    // absolutely positioned from the bottom so expansion grows upward.
    return (
      <div
        className={cn("w-full relative", className)}
        style={headerHeight ? { height: headerHeight } : undefined}
      >
        <div className="absolute bottom-0 left-0 right-0 z-20">
          <div className="overflow-hidden rounded-lg border border-border/60 bg-background/50 backdrop-blur-sm shadow-sm">
            {headerButton}
            {expandedContent}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("w-full", className)}>
      <div className="overflow-hidden rounded-lg border border-border/60 bg-background/50 backdrop-blur-sm">
        {headerButton}
        {expandedContent}
      </div>
    </div>
  );
};
