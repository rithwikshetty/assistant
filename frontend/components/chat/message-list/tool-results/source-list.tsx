
/**
 * Shared source-list primitives used by knowledge, web-search, and other
 * tool-result displays.
 *
 * Three building blocks:
 *  - SourceList / SourceItem  — bordered reference-row list
 *  - FileTypeBadge            — color-coded file-extension pill
 *  - ContentDisclosure        — toggle + scroll-contained markdown area
 */

import { useState, type FC, type ReactNode } from "react";
import {
  FileText,
  CaretRight,
  CaretDown,
  ArrowSquareOut,
  Quotes,
} from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/markdown/markdown-content";

// ============================================================================
// SourceList
// ============================================================================

export type SourceItem = {
  /** Stable React key */
  key: string;
  /** Primary display text — filename, page title, etc. */
  label: string;
  /** When present the entire row becomes a link */
  href?: string;
  /** Trailing secondary text — page summary, hostname, etc. */
  secondary?: string;
  /** Leading visual — FileTypeBadge, icon, etc. */
  leading?: ReactNode;
};

export const SourceList: FC<{ items: SourceItem[]; className?: string }> = ({
  items,
  className,
}) => {
  if (items.length === 0) return null;

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="type-size-10 font-semibold text-muted-foreground uppercase tracking-wider">
        Sources
      </div>
      <div className="rounded-md border border-border/40 divide-y divide-border/30 overflow-hidden">
        {items.map((item) => {
          const isLinked = !!item.href;
          const Row = isLinked ? "a" : "div";
          const linkProps = isLinked
            ? {
                href: item.href!,
                target: "_blank" as const,
                rel: "noopener noreferrer",
              }
            : {};

          return (
            <Row
              key={item.key}
              className={cn(
                "group/row flex items-center gap-2.5 px-3 py-2 transition-colors",
                isLinked
                  ? "hover:bg-muted/50 cursor-pointer"
                  : "bg-transparent",
              )}
              {...linkProps}
            >
              {item.leading}
              <span
                className={cn(
                  "flex-1 min-w-0 type-size-14 truncate",
                  isLinked
                    ? "text-foreground/90 group-hover/row:text-foreground"
                    : "text-foreground/60",
                )}
              >
                {item.label}
              </span>
              {item.secondary && (
                <span className="type-size-10 text-muted-foreground whitespace-nowrap">
                  {item.secondary}
                </span>
              )}
              {isLinked && (
                <ArrowSquareOut className="h-3 w-3 text-muted-foreground/40 group-hover/row:text-muted-foreground transition-colors flex-shrink-0" />
              )}
            </Row>
          );
        })}
      </div>
    </div>
  );
};

// ============================================================================
// FileTypeBadge
// ============================================================================

const getFileExtension = (filename: string): string => {
  const dotIndex = filename.lastIndexOf(".");
  if (dotIndex < 0 || dotIndex === filename.length - 1) return "";
  return filename.slice(dotIndex + 1).toLowerCase();
};

const FILE_TYPE_COLORS: Record<string, string> = {
  pdf: "bg-red-500/15 text-red-700 dark:bg-red-900/40 dark:text-red-400",
  doc: "bg-orange-500/15 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400",
  docx: "bg-orange-500/15 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400",
  ppt: "bg-amber-500/15 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  pptx: "bg-amber-500/15 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
  xls: "bg-emerald-500/15 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  xlsx: "bg-emerald-500/15 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  csv: "bg-emerald-500/15 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  msg: "bg-stone-500/15 text-stone-700 dark:bg-stone-800/50 dark:text-stone-400",
  eml: "bg-stone-500/15 text-stone-700 dark:bg-stone-800/50 dark:text-stone-400",
  txt: "bg-slate-500/15 text-slate-600 dark:bg-slate-800/50 dark:text-slate-400",
  md: "bg-slate-500/15 text-slate-600 dark:bg-slate-800/50 dark:text-slate-400",
};

const DEFAULT_FILE_COLOR = "bg-muted text-muted-foreground";

export const FileTypeBadge: FC<{ filename: string }> = ({ filename }) => {
  const ext = getFileExtension(filename);
  if (!ext) {
    return (
      <FileText className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
    );
  }
  const colorClass = FILE_TYPE_COLORS[ext] || DEFAULT_FILE_COLOR;
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded px-1.5 py-0.5",
        "type-size-10 font-semibold uppercase tracking-wide leading-none",
        "min-w-[2rem] flex-shrink-0",
        colorClass,
      )}
    >
      {ext}
    </span>
  );
};

// ============================================================================
// ContentDisclosure
// ============================================================================

export const ContentDisclosure: FC<{
  content: string;
  label?: string;
  className?: string;
}> = ({ content, label = "Retrieved content", className }) => {
  const [visible, setVisible] = useState(false);

  if (!content) return null;

  return (
    <div className={cn("pt-0.5", className)}>
      <button
        type="button"
        onClick={() => setVisible(!visible)}
        className="flex items-center gap-1.5 type-size-12 text-muted-foreground/70 hover:text-muted-foreground transition-colors"
      >
        {visible ? (
          <CaretDown className="h-3 w-3" />
        ) : (
          <CaretRight className="h-3 w-3" />
        )}
        <Quotes className="h-3 w-3" />
        <span>{label}</span>
      </button>

      {visible && (
        <div
          className={cn(
            "mt-2 rounded-md border border-border/30",
            "bg-muted/20 dark:bg-muted/10",
            "max-h-72 overflow-y-auto scrollbar-thin",
          )}
        >
          <div className="px-3.5 py-3 type-size-14 leading-relaxed text-foreground/80">
            <MarkdownContent content={content} />
          </div>
        </div>
      )}
    </div>
  );
};
