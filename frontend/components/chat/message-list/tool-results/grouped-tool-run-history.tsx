import { type FC, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { MessageContentPart } from "../types";

type ToolCallPart = MessageContentPart & { type: "tool-call" };

type GroupedToolRunHistoryProps = {
  parts: ToolCallPart[];
  renderEntry: (part: ToolCallPart, index: number) => ReactNode;
  className?: string;
};

const getPartKey = (part: ToolCallPart, index: number): string =>
  part.toolCallId || `${part.toolName}-${index}`;

export const GroupedToolRunHistory: FC<GroupedToolRunHistoryProps> = ({
  parts,
  renderEntry,
  className,
}) => (
  <div className={cn("space-y-2", className)}>
    {parts.map((part, index) => (
      <div key={getPartKey(part, index)}>{renderEntry(part, index)}</div>
    ))}
  </div>
);
