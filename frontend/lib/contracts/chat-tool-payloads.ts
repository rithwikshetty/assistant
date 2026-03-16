import {
  parseRequestUserInputRequestPayload,
  parseRequestUserInputResultPayload,
  type InteractiveRequestPayload,
  type InteractiveResultPayload,
} from "./chat-interactive";
import {
  parseChartToolResultPayload,
  parseGanttToolResultPayload,
  type VisibleToolResultPayload,
} from "./chat-visible-tools";
import {
  parseCalculationResultPayload,
  parseKnowledgeResultPayload,
  parseTasksResultPayload,
  parseWebSearchResultPayload,
  type GroupedToolResultPayload,
} from "./chat-grouped-tools";
import {
  parseExecuteCodeResultPayload,
  parseFileReadResultPayload,
  parseSkillResultPayload,
  type SpecializedToolResultPayload,
} from "./chat-specialized-tools";
import {
  getToolRequestSchemaKind,
  getToolResultSchemaKind,
} from "@/lib/tools/constants";

export type KnownToolRequestPayload =
  | InteractiveRequestPayload;

export type KnownToolResultPayload =
  | InteractiveResultPayload
  | VisibleToolResultPayload
  | GroupedToolResultPayload
  | SpecializedToolResultPayload;

export function parseToolRequestPayloadForTool(
  toolName: unknown,
  raw: unknown,
  label: string = "toolRequest",
): KnownToolRequestPayload {
  const schemaKind = getToolRequestSchemaKind(toolName);
  if (!schemaKind) {
    throw new Error(`${label}.toolName must be a supported tool`);
  }
  switch (schemaKind) {
    case "requestUserInput":
      return parseRequestUserInputRequestPayload(raw, label);
    default:
      throw new Error(`${label}.toolName must be a supported tool`);
  }
}

export function parseToolResultPayloadForTool(
  toolName: unknown,
  raw: unknown,
  label: string = "toolResult",
): KnownToolResultPayload {
  const schemaKind = getToolResultSchemaKind(toolName);
  if (!schemaKind) {
    throw new Error(`${label}.toolName must be a supported tool`);
  }
  switch (schemaKind) {
    case "webSearch":
      return parseWebSearchResultPayload(raw, label);
    case "knowledge":
      return parseKnowledgeResultPayload(raw, label);
    case "calculation":
      return parseCalculationResultPayload(raw, label);
    case "tasks":
      return parseTasksResultPayload(raw, label);
    case "chart":
      return parseChartToolResultPayload(raw, label);
    case "gantt":
      return parseGanttToolResultPayload(raw, label);
    case "fileRead":
      return parseFileReadResultPayload(raw, label);
    case "executeCode":
      return parseExecuteCodeResultPayload(raw, label);
    case "skill":
      return parseSkillResultPayload(raw, label);
    case "requestUserInput":
      return parseRequestUserInputResultPayload(raw, label);
    default:
      throw new Error(`${label}.toolName must be a supported tool`);
  }
}
