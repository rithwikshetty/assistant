
/**
 * TextPart - Renders text content with markdown
 */

import { type FC } from "react";
import { MarkdownContent } from "@/components/markdown/markdown-content";

type TextPartProps = {
  text: string;
};

export const TextPart: FC<TextPartProps> = ({ text }) => {
  if (!text || !text.trim()) return null;

  return (
    <div className="prose dark:prose-invert max-w-none">
      <MarkdownContent content={text} />
    </div>
  );
};

