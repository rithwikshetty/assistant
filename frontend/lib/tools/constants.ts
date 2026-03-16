import {
  CHAT_INTERACTIVE_TOOL_NAMES,
  type ChatToolName,
} from "@/lib/chat/generated/ws-contract";

export const TOOL = {
  WEB_SEARCH: "retrieval_web_search",
  LOAD_SKILL: "load_skill",
  SEARCH_PROJECT_FILES: "retrieval_project_files",
  FILE_READER: "file_read",
  CALCULATE: "calc_basic",
  APPLY_CONTINGENCY: "calc_contingency",
  CALCULATE_ESCALATION: "calc_escalation",
  CALCULATE_UNIT_RATE: "calc_unit_rate",
  PERCENTAGE_OF_TOTAL: "calc_percentage_of_total",
  CALCULATE_VARIANCE: "calc_variance",
  CREATE_CHART: "viz_create_chart",
  CREATE_GANTT: "viz_create_gantt",
  TASKS: "tasks",
  EXECUTE_CODE: "execute_code",
  REQUEST_USER_INPUT: "request_user_input",
} as const satisfies Record<string, ChatToolName>;

export type ToolName = ChatToolName;
export type ToolGroupKey = "KNOWLEDGE" | "CALCULATION" | ToolName;
export type ToolIconKey =
  | "globe"
  | "book"
  | "blocks"
  | "file-search"
  | "search"
  | "chart"
  | "calendar"
  | "tasks"
  | "user-input"
  | "code"
  | "calculator"
  | "file-text";
export type ToolArgsSchemaKind =
  | "query"
  | "record"
  | "retrievalProjectFiles"
  | "fileRead"
  | "tasks"
  | "loadSkill"
  | "chart"
  | "gantt"
  | "requestUserInput"
  | "executeCode";
export type ToolResultSchemaKind =
  | "webSearch"
  | "knowledge"
  | "calculation"
  | "tasks"
  | "fileRead"
  | "executeCode"
  | "skill"
  | "chart"
  | "gantt"
  | "requestUserInput";
export type ToolRequestSchemaKind = "requestUserInput";

export type ToolDefinition = {
  name: ToolName;
  displayName: string;
  groupKey: ToolGroupKey;
  visible: boolean;
  iconKey: ToolIconKey;
  argsSchema: ToolArgsSchemaKind;
  resultSchema: ToolResultSchemaKind;
  requestSchema?: ToolRequestSchemaKind | null;
  composerInteractive?: boolean;
};

const INTERACTIVE_TOOL_NAME_SET = new Set<string>(CHAT_INTERACTIVE_TOOL_NAMES);

export const TOOL_REGISTRY: Record<ToolName, ToolDefinition> = {
  [TOOL.WEB_SEARCH]: {
    name: TOOL.WEB_SEARCH,
    displayName: "Web Search",
    groupKey: TOOL.WEB_SEARCH,
    visible: false,
    iconKey: "globe",
    argsSchema: "query",
    resultSchema: "webSearch",
  },
  [TOOL.LOAD_SKILL]: {
    name: TOOL.LOAD_SKILL,
    displayName: "Load Skill",
    groupKey: TOOL.LOAD_SKILL,
    visible: false,
    iconKey: "blocks",
    argsSchema: "loadSkill",
    resultSchema: "skill",
  },
  [TOOL.SEARCH_PROJECT_FILES]: {
    name: TOOL.SEARCH_PROJECT_FILES,
    displayName: "Project Files",
    groupKey: "KNOWLEDGE",
    visible: false,
    iconKey: "search",
    argsSchema: "retrievalProjectFiles",
    resultSchema: "knowledge",
  },
  [TOOL.FILE_READER]: {
    name: TOOL.FILE_READER,
    displayName: "File Reader",
    groupKey: TOOL.FILE_READER,
    visible: false,
    iconKey: "file-search",
    argsSchema: "fileRead",
    resultSchema: "fileRead",
  },
  [TOOL.CALCULATE]: {
    name: TOOL.CALCULATE,
    displayName: "Calculate",
    groupKey: "CALCULATION",
    visible: false,
    iconKey: "calculator",
    argsSchema: "record",
    resultSchema: "calculation",
  },
  [TOOL.APPLY_CONTINGENCY]: {
    name: TOOL.APPLY_CONTINGENCY,
    displayName: "Apply Contingency",
    groupKey: "CALCULATION",
    visible: false,
    iconKey: "calculator",
    argsSchema: "record",
    resultSchema: "calculation",
  },
  [TOOL.CALCULATE_ESCALATION]: {
    name: TOOL.CALCULATE_ESCALATION,
    displayName: "Calculate Escalation",
    groupKey: "CALCULATION",
    visible: false,
    iconKey: "calculator",
    argsSchema: "record",
    resultSchema: "calculation",
  },
  [TOOL.CALCULATE_UNIT_RATE]: {
    name: TOOL.CALCULATE_UNIT_RATE,
    displayName: "Unit Rate",
    groupKey: "CALCULATION",
    visible: false,
    iconKey: "calculator",
    argsSchema: "record",
    resultSchema: "calculation",
  },
  [TOOL.PERCENTAGE_OF_TOTAL]: {
    name: TOOL.PERCENTAGE_OF_TOTAL,
    displayName: "Percentage",
    groupKey: "CALCULATION",
    visible: false,
    iconKey: "calculator",
    argsSchema: "record",
    resultSchema: "calculation",
  },
  [TOOL.CALCULATE_VARIANCE]: {
    name: TOOL.CALCULATE_VARIANCE,
    displayName: "Variance",
    groupKey: "CALCULATION",
    visible: false,
    iconKey: "calculator",
    argsSchema: "record",
    resultSchema: "calculation",
  },
  [TOOL.CREATE_CHART]: {
    name: TOOL.CREATE_CHART,
    displayName: "Create Chart",
    groupKey: TOOL.CREATE_CHART,
    visible: true,
    iconKey: "chart",
    argsSchema: "chart",
    resultSchema: "chart",
  },
  [TOOL.CREATE_GANTT]: {
    name: TOOL.CREATE_GANTT,
    displayName: "Gantt Chart",
    groupKey: TOOL.CREATE_GANTT,
    visible: true,
    iconKey: "calendar",
    argsSchema: "gantt",
    resultSchema: "gantt",
  },
  [TOOL.TASKS]: {
    name: TOOL.TASKS,
    displayName: "Tasks",
    groupKey: TOOL.TASKS,
    visible: false,
    iconKey: "tasks",
    argsSchema: "tasks",
    resultSchema: "tasks",
  },
  [TOOL.EXECUTE_CODE]: {
    name: TOOL.EXECUTE_CODE,
    displayName: "Code Execution",
    groupKey: TOOL.EXECUTE_CODE,
    visible: false,
    iconKey: "code",
    argsSchema: "executeCode",
    resultSchema: "executeCode",
  },
  [TOOL.REQUEST_USER_INPUT]: {
    name: TOOL.REQUEST_USER_INPUT,
    displayName: "Gathering Input",
    groupKey: TOOL.REQUEST_USER_INPUT,
    visible: false,
    iconKey: "user-input",
    argsSchema: "requestUserInput",
    resultSchema: "requestUserInput",
    requestSchema: "requestUserInput",
    composerInteractive: true,
  },
};

function fallbackToolLabel(toolName: string): string {
  return toolName.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function getToolDefinition(toolName: unknown): ToolDefinition | null {
  if (typeof toolName !== "string") return null;
  return TOOL_REGISTRY[toolName as ToolName] ?? null;
}

export function getToolDisplayName(toolName: string): string {
  return getToolDefinition(toolName)?.displayName ?? fallbackToolLabel(toolName);
}

export function getToolGroupKey(toolName: string): string {
  return getToolDefinition(toolName)?.groupKey ?? toolName;
}

export function isVisibleToolName(toolName: string): boolean {
  return getToolDefinition(toolName)?.visible === true;
}

export function getToolIconKey(toolName: string): ToolIconKey {
  return getToolDefinition(toolName)?.iconKey ?? "file-text";
}

export function getToolArgsSchemaKind(toolName: unknown): ToolArgsSchemaKind | null {
  return getToolDefinition(toolName)?.argsSchema ?? null;
}

export function getToolResultSchemaKind(toolName: unknown): ToolResultSchemaKind | null {
  return getToolDefinition(toolName)?.resultSchema ?? null;
}

export function getToolRequestSchemaKind(toolName: unknown): ToolRequestSchemaKind | null {
  return getToolDefinition(toolName)?.requestSchema ?? null;
}

export function isToolInGroup(toolName: unknown, groupKey: Exclude<ToolGroupKey, ToolName>): boolean {
  return getToolDefinition(toolName)?.groupKey === groupKey;
}

export function isKnowledgeToolName(toolName: unknown): toolName is ToolName {
  return isToolInGroup(toolName, "KNOWLEDGE");
}

export function isCalculationToolName(toolName: unknown): toolName is ToolName {
  return isToolInGroup(toolName, "CALCULATION");
}

export function isInteractiveToolName(toolName: unknown): toolName is ToolName {
  return typeof toolName === "string" && INTERACTIVE_TOOL_NAME_SET.has(toolName);
}

export function isComposerInteractiveToolName(toolName: unknown): toolName is ToolName {
  return getToolDefinition(toolName)?.composerInteractive === true;
}
