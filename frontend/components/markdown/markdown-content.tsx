
/**
 * MarkdownContent - Standalone markdown renderer
 *
 * Used by the backend-driven chat system.
 */

import { FC, memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

// ============================================================================
// Types
// ============================================================================

export type MarkdownContentProps = {
  /** The markdown content to render */
  content: string;
  /** Additional class names */
  className?: string;
};

// ============================================================================
// Markdown Components
// ============================================================================

const markdownComponents = {
  // Links open in new tab
  a: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 hover:text-primary/80"
      {...props}
    >
      {children}
    </a>
  ),
  // Code blocks with styling
  code: ({ className, children, ...props }: React.HTMLAttributes<HTMLElement>) => {
    const isInline = !className?.includes("language-");
    if (isInline) {
      return (
        <code
          className="rounded bg-muted px-1.5 py-0.5 type-size-12 font-mono"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code className={cn("block", className)} {...props}>
        {children}
      </code>
    );
  },
  // Pre blocks for code
  pre: ({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) => (
    <pre
      className="overflow-x-auto rounded-lg bg-zinc-900 p-3 type-size-12 text-zinc-100"
      {...props}
    >
      {children}
    </pre>
  ),
  // Paragraphs
  p: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="mb-2.5 last:mb-0" {...props}>
      {children}
    </p>
  ),
  // Headings
  h1: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className="mb-4 mt-6 type-size-32 font-bold first:mt-0" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className="mb-3 mt-5 type-size-24 font-semibold first:mt-0" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className="mb-2 mt-4 type-size-20 font-semibold first:mt-0" {...props}>
      {children}
    </h3>
  ),
  // Lists
  ul: ({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) => (
    <ul className="mb-2.5 list-disc pl-5 last:mb-0" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }: React.HTMLAttributes<HTMLOListElement>) => (
    <ol className="mb-2.5 list-decimal pl-5 last:mb-0" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }: React.HTMLAttributes<HTMLLIElement>) => (
    <li className="mb-1 last:mb-0" {...props}>
      {children}
    </li>
  ),
  // Blockquotes
  blockquote: ({ children, ...props }: React.HTMLAttributes<HTMLQuoteElement>) => (
    <blockquote
      className="mb-2.5 border-l-4 border-muted-foreground/30 pl-3.5 italic text-muted-foreground last:mb-0"
      {...props}
    >
      {children}
    </blockquote>
  ),
  // Tables
  table: ({ children, ...props }: React.HTMLAttributes<HTMLTableElement>) => (
    <div className="mb-2.5 overflow-hidden rounded-md border border-border shadow-sm last:mb-0">
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse" {...props}>
          {children}
        </table>
      </div>
    </div>
  ),
  th: ({ children, ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <th
      className="border-b border-r border-border last:border-r-0 bg-muted/50 px-2.5 py-1.5 text-left type-size-14 font-semibold"
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ children, ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <td className="border-b border-r border-border last:border-r-0 px-2.5 py-1.5 type-size-14" {...props}>
      {children}
    </td>
  ),
  // Horizontal rule
  hr: (props: React.HTMLAttributes<HTMLHRElement>) => (
    <hr className="my-3 border-border" {...props} />
  ),
  // Strong/bold
  strong: ({ children, ...props }: React.HTMLAttributes<HTMLElement>) => (
    <strong className="font-semibold" {...props}>
      {children}
    </strong>
  ),
  // Emphasis/italic
  em: ({ children, ...props }: React.HTMLAttributes<HTMLElement>) => (
    <em className="italic" {...props}>
      {children}
    </em>
  ),
};

// ============================================================================
// MarkdownContent Component
// ============================================================================

export const MarkdownContent: FC<MarkdownContentProps> = memo(
  ({ content, className }) => {
    // Memoize the rendered content
    const rendered = useMemo(
      () => (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
          components={markdownComponents}
        >
          {content}
        </ReactMarkdown>
      ),
      [content]
    );

    return <div className={cn("aui-md type-size-14 leading-[1.6]", className)}>{rendered}</div>;
  }
);

MarkdownContent.displayName = "MarkdownContent";

export default MarkdownContent;
