
import { Check as CheckIcon, Copy as CopyIcon } from "@phosphor-icons/react";
import { FC, useState, HTMLAttributes, memo, createContext, useContext } from "react";

import { TooltipIconButton } from "@/components/tools/tooltip-icon-button";
import { cn } from "@/lib/utils";

type CodeHeaderProps = {
  language: string;
  code: string;
};

const CodeBlockContext = createContext(false);
const useIsMarkdownCodeBlock = () => useContext(CodeBlockContext);

function memoizeMarkdownComponents<T extends Record<string, FC<any>>>(components: T): T {
  const memoized = {} as T;
  for (const key in components) {
    if (Object.prototype.hasOwnProperty.call(components, key)) {
      const componentKey = key as keyof T;
      memoized[componentKey] = memo(components[componentKey]) as unknown as T[keyof T];
    }
  }
  return memoized;
}

const useCopyToClipboard = ({
  copiedDuration = 3000,
}: {
  copiedDuration?: number;
} = {}) => {
  const [isCopied, setIsCopied] = useState<boolean>(false);

  const copyToClipboard = (value: string) => {
    if (!value) return;

    navigator.clipboard.writeText(value).then(() => {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), copiedDuration);
    });
  };

  return { isCopied, copyToClipboard };
};

export const MarkdownCodeHeader: FC<CodeHeaderProps> = ({ language, code }) => {
  const { isCopied, copyToClipboard } = useCopyToClipboard();
  const onCopy = () => {
    if (!code || isCopied) return;
    copyToClipboard(code);
  };

  return (
    <div className="flex items-center justify-between gap-4 rounded-t-lg bg-stone-900 dark:bg-stone-950 px-4 py-2.5 type-size-14 font-medium text-stone-300">
      <span className="lowercase type-size-12 font-mono text-stone-500">{language}</span>
      <TooltipIconButton tooltip="Copy" onClick={onCopy}>
        {!isCopied && <CopyIcon className="size-3.5" />}
        {isCopied && <CheckIcon className="size-3.5 text-emerald-400" />}
      </TooltipIconButton>
    </div>
  );
};

const baseMarkdownComponents = {
  h1: ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className={cn("mb-2 mt-4 scroll-m-20 font-[family-name:var(--font-display)] type-size-32 font-bold tracking-tight first:mt-0 last:mb-0 text-foreground", className)} {...props} />
  ),
  h2: ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className={cn("mb-1.5 mt-3 scroll-m-20 font-[family-name:var(--font-display)] type-size-24 font-semibold tracking-tight first:mt-0 last:mb-0 text-foreground", className)} {...props} />
  ),
  h3: ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className={cn("mb-1 mt-2.5 scroll-m-20 font-[family-name:var(--font-display)] type-size-20 font-semibold tracking-tight first:mt-0 last:mb-0 text-foreground", className)} {...props} />
  ),
  h4: ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
    <h4 className={cn("mb-1 mt-2 scroll-m-20 type-size-16 font-semibold tracking-tight first:mt-0 last:mb-0 text-foreground", className)} {...props} />
  ),
  h5: ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
    <h5 className={cn("mb-0.5 mt-1.5 type-size-14 font-semibold first:mt-0 last:mb-0 text-foreground", className)} {...props} />
  ),
  h6: ({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) => (
    <h6 className={cn("mb-0.5 mt-1.5 type-size-12 font-semibold first:mt-0 last:mb-0 text-foreground", className)} {...props} />
  ),
  p: ({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) => (
    <p className={cn("mb-1.5 type-size-14 text-foreground/85 first:mt-0 last:mb-0 leading-relaxed", className)} {...props} />
  ),
  a: ({ className, ...props }: HTMLAttributes<HTMLAnchorElement>) => (
    <a className={cn("text-primary font-medium underline underline-offset-4 decoration-primary/30 hover:decoration-primary/60 transition-colors cursor-pointer", className)} target="_blank" rel="noopener noreferrer" {...props} />
  ),
  blockquote: ({ className, ...props }: HTMLAttributes<HTMLQuoteElement>) => (
    <blockquote className={cn("border-l-3 border-primary/25 pl-4 italic my-2 text-muted-foreground bg-primary/3 py-1.5 rounded-r-lg", className)} {...props} />
  ),
  ul: ({ className, ...props }: HTMLAttributes<HTMLUListElement>) => (
    <ul className={cn("my-1.5 ml-6 list-disc space-y-0.5 type-size-14 text-foreground/85 marker:text-primary/50", className)} {...props} />
  ),
  ol: ({ className, ...props }: HTMLAttributes<HTMLOListElement>) => (
    <ol className={cn("my-1.5 ml-6 list-decimal space-y-0.5 type-size-14 text-foreground/85 marker:text-primary/70 marker:font-medium", className)} {...props} />
  ),
  hr: ({ className, ...props }: HTMLAttributes<HTMLHRElement>) => (
    <hr className={cn("my-3 border-border/30", className)} {...props} />
  ),
  table: ({ className, ...props }: HTMLAttributes<HTMLTableElement>) => (
    <div className="my-3 max-w-full overflow-x-auto rounded-lg border border-border/30">
      <table
        className={cn(
          "w-full min-w-[640px] table-auto border-collapse type-size-14 [&_tr:last-child_td]:border-b-0",
          className,
        )}
        {...props}
      />
    </div>
  ),
  th: ({ className, ...props }: HTMLAttributes<HTMLTableCellElement>) => (
    <th className={cn("bg-muted/30 px-4 py-3 text-left font-semibold text-foreground border-b border-border/30 [&[align=center]]:text-center [&[align=right]]:text-right", className)} {...props} />
  ),
  td: ({ className, ...props }: HTMLAttributes<HTMLTableCellElement>) => (
    <td
      className={cn(
        "border-b border-border/20 px-4 py-3 text-left whitespace-pre-wrap break-words text-foreground/80 [&[align=center]]:text-center [&[align=right]]:text-right",
        className,
      )}
      {...props}
    />
  ),
  tr: ({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) => (
    <tr className={cn("m-0 p-0 hover:bg-muted/15 transition-colors", className)} {...props} />
  ),
  sup: ({ className, ...props }: HTMLAttributes<HTMLElement>) => (
    <sup className={cn("type-size-12 [&>a]:no-underline text-muted-foreground", className)} {...props} />
  ),
  pre: function Pre({ className, children, ...props }: HTMLAttributes<HTMLPreElement>) {
    return (
      <pre className={cn("overflow-x-auto rounded-lg bg-stone-950 p-4 text-stone-200 border border-stone-800/50 my-2.5 font-mono", className)} {...props}>
        {children}
      </pre>
    );
  },
  code: function Code({ className, ...props }: HTMLAttributes<HTMLElement>) {
    const isCodeBlock = useIsMarkdownCodeBlock();
    return (
      <code
        className={cn(!isCodeBlock && "bg-primary/6 dark:bg-primary/10 rounded-md px-1.5 py-0.5 font-mono type-size-14 text-foreground/90", className)}
        {...props}
      />
    );
  },
};

export const markdownComponents = memoizeMarkdownComponents({
  ...baseMarkdownComponents,
  CodeHeader: MarkdownCodeHeader,
});

export const baseComponentsWithoutCodeHeader = memoizeMarkdownComponents(baseMarkdownComponents);
