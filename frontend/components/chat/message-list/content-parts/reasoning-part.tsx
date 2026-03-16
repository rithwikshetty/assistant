
/**
 * ReasoningPart - Renders reasoning/thinking blocks
 */

import { type CSSProperties, type FC } from "react";

type ReasoningPartProps = {
  isStreaming?: boolean;
};

const shimmerStyle: CSSProperties = {
  background:
    "linear-gradient(90deg, currentColor 0%, rgba(255, 255, 255, 0.3) 25%, currentColor 50%, currentColor 100%)",
  backgroundSize: "200% 100%",
  backgroundClip: "text",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  animation: "shimmer 2s linear infinite",
};

export const ReasoningPart: FC<ReasoningPartProps> = ({ isStreaming }) => {
  if (!isStreaming) {
    return null;
  }

  return (
    <div className="type-size-14 text-muted-foreground tool-connectable">
      <div className="flex items-center max-w-full">
        <span className="font-medium truncate max-w-[500px]" style={shimmerStyle}>
          Thinking
        </span>
      </div>
    </div>
  );
};
