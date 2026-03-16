import { type FC } from "react";
import { TOOL } from "@/lib/tools/constants";
import type { MessageContentPart } from "./types";
import { getContentPartStableKey } from "./utils";
import { ContentPart } from "./content-parts";
import {
  WebSearchGroupDisplay,
  KnowledgeGroupDisplay,
  CalculationGroupDisplay,
  FileReaderGroupDisplay,
  TasksGroupDisplay,
  SkillGroupDisplay,
  ExecuteCodeGroupDisplay,
} from "./tool-results";

type ToolGroupRendererProps = {
  groupKey: string;
  parts: MessageContentPart[];
};

export const ToolGroupRenderer: FC<ToolGroupRendererProps> = ({ groupKey, parts }) => {
  // Render grouped displays for known tool families, even when there's only one part.
  if (groupKey === "KNOWLEDGE") {
    return <KnowledgeGroupDisplay parts={parts} />;
  }

  if (groupKey === "CALCULATION") {
    return <CalculationGroupDisplay parts={parts} />;
  }

  if (groupKey === TOOL.WEB_SEARCH) {
    return <WebSearchGroupDisplay parts={parts} />;
  }

  if (groupKey === TOOL.FILE_READER) {
    return <FileReaderGroupDisplay parts={parts} />;
  }

  if (groupKey === TOOL.TASKS) {
    return <TasksGroupDisplay parts={parts} />;
  }

  if (groupKey === TOOL.LOAD_SKILL) {
    return <SkillGroupDisplay parts={parts} />;
  }

  if (groupKey === TOOL.EXECUTE_CODE) {
    return <ExecuteCodeGroupDisplay parts={parts} />;
  }

  // Unknown/specialized tool: render directly for one part.
  if (parts.length === 1) {
    return <ContentPart part={parts[0]} />;
  }

  // Default: render each part as its own visible row.
  return (
    <div className="space-y-0.5">
      {parts.map((part, idx) => (
        <ContentPart key={getContentPartStableKey(part, idx)} part={part} />
      ))}
    </div>
  );
};
