
/**
 * ContentPart - Routes to appropriate part renderer based on type
 */

import { type FC } from "react";
import type { MessageContentPart } from "../types";
import { TextPart } from "./text-part";
import { ReasoningPart } from "./reasoning-part";
import { ToolCallPart } from "./tool-call-part";

type ContentPartProps = {
  part: MessageContentPart;
};

export const ContentPart: FC<ContentPartProps> = ({ part }) => {
  switch (part.type) {
    case "text":
      return <TextPart text={part.text} />;
    case "divider":
      return (
        <div className="my-2 flex items-center gap-3 text-muted-foreground">
          <span className="h-px flex-1 bg-border/50" />
          <span className="type-size-14 font-medium">{part.label}</span>
          <span className="h-px flex-1 bg-border/50" />
        </div>
      );
    case "tool-call":
      return (
        <ToolCallPart
          toolName={part.toolName}
          toolCallId={part.toolCallId}
          args={part.args}
          result={part.result}
          isError={part.isError}
        />
      );
    case "reasoning":
      return (
        <ReasoningPart
          isStreaming={(part.metadata as { streaming?: boolean } | undefined)?.streaming}
        />
      );
    default:
      return null;
  }
};
