import type {
  UserInputQuestionOptionPayload,
  UserInputQuestionPayload,
} from "./chat-interactive";
import {
  type JsonRecord,
  expectRecord,
  readString,
  readNullableString,
  readNullableBoolean,
  readNullableNumber,
  readNullableStringArray,
} from "./contract-utils";
import { getToolArgsSchemaKind } from "@/lib/tools/constants";

const TASK_ACTIONS = ["list", "get", "create", "update", "complete", "delete", "comment"] as const;
const TASK_STATUSES = ["todo", "in_progress", "done"] as const;
const TASK_PRIORITIES = ["low", "medium", "high", "urgent"] as const;
const TASK_VIEWS = ["active", "completed", "all"] as const;
const TASK_SCOPES = ["all", "created", "assigned"] as const;
const CHART_TOOL_TYPES = ["bar", "line", "pie", "area", "stacked_bar", "waterfall"] as const;
const GANTT_VIEW_MODES = ["Day", "Week", "Month", "Year"] as const;

export type QueryToolArguments = {
  query: string;
};

export type RetrievalProjectFilesToolArguments = {
  query?: string | null;
  limit?: number | null;
};

export type FileReadToolArguments = {
  file_id: string;
  start?: number | null;
  length?: number | null;
  full?: boolean | null;
};

export type TasksToolArguments = {
  action?: (typeof TASK_ACTIONS)[number] | null;
  id?: string | null;
  title?: string | null;
  description?: string | null;
  status?: (typeof TASK_STATUSES)[number] | null;
  priority?: (typeof TASK_PRIORITIES)[number] | null;
  due_at?: string | null;
  category?: string | null;
  conversation_id?: string | null;
  assignee_ids?: string[] | null;
  assignee_emails?: string[] | null;
  content?: string | null;
  view?: (typeof TASK_VIEWS)[number] | null;
  scope?: (typeof TASK_SCOPES)[number] | null;
  due_from?: string | null;
  due_to?: string | null;
  limit?: number | null;
};

export type LoadSkillToolArguments = {
  skill_id: string;
};

export type ChartToolArguments = {
  type: (typeof CHART_TOOL_TYPES)[number];
  title: string;
  data: JsonRecord[];
  x_axis_key?: string | null;
  data_keys?: string[] | null;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  colors?: string[] | null;
};

export type GanttTaskToolArguments = {
  id: string;
  name: string;
  start: string;
  end: string;
  progress?: number | null;
  dependencies?: string | null;
  custom_bar_color?: string | null;
};

export type GanttToolArguments = {
  title: string;
  tasks: GanttTaskToolArguments[];
  view_mode?: (typeof GANTT_VIEW_MODES)[number] | null;
  readonly?: boolean | null;
};

export type RequestUserInputToolArguments = {
  title: string;
  prompt: string;
  questions: UserInputQuestionPayload[];
  submit_label?: string | null;
};

export type ExecuteCodeToolArguments = {
  code: string;
  file_ids?: string[] | null;
  skill_assets?: string[] | null;
  timeout?: number | null;
};

export type KnownToolArgumentsPayload =
  | QueryToolArguments
  | RetrievalProjectFilesToolArguments
  | FileReadToolArguments
  | TasksToolArguments
  | LoadSkillToolArguments
  | ChartToolArguments
  | GanttToolArguments
  | RequestUserInputToolArguments
  | ExecuteCodeToolArguments;

function parseUserInputQuestionOptionPayload(raw: unknown, label: string): UserInputQuestionOptionPayload {
  const record = expectRecord(raw, label);
  return {
    label: readString(record, "label", label),
    description: readString(record, "description", label),
  };
}

function parseUserInputQuestionPayload(raw: unknown, label: string): UserInputQuestionPayload {
  const record = expectRecord(raw, label);
  const optionsRaw = record.options;
  if (!Array.isArray(optionsRaw) || optionsRaw.length < 2) {
    throw new Error(`${label}.options must contain at least 2 options`);
  }
  return {
    id: readString(record, "id", label),
    question: readString(record, "question", label),
    options: optionsRaw.map((entry, index) =>
      parseUserInputQuestionOptionPayload(entry, `${label}.options[${index}]`),
    ),
  };
}

export function parseQueryToolArguments(
  raw: unknown,
  label: string = "toolArguments.query",
): QueryToolArguments {
  const record = expectRecord(raw, label);
  return {
    query: readString(record, "query", label),
  };
}

export function parseRetrievalProjectFilesToolArguments(
  raw: unknown,
  label: string = "toolArguments.retrievalProjectFiles",
): RetrievalProjectFilesToolArguments {
  const record = expectRecord(raw, label);
  return {
    query: readNullableString(record, "query", label),
    limit: readNullableNumber(record, "limit", label),
  };
}

export function parseFileReadToolArguments(
  raw: unknown,
  label: string = "toolArguments.fileRead",
): FileReadToolArguments {
  const record = expectRecord(raw, label);
  return {
    file_id: readString(record, "file_id", label),
    start: readNullableNumber(record, "start", label),
    length: readNullableNumber(record, "length", label),
    full: readNullableBoolean(record, "full", label),
  };
}

export function parseTasksToolArguments(
  raw: unknown,
  label: string = "toolArguments.tasks",
): TasksToolArguments {
  const record = expectRecord(raw, label);
  return {
    action: readNullableEnumString(record, "action", label, TASK_ACTIONS),
    id: readNullableString(record, "id", label),
    title: readNullableString(record, "title", label),
    description: readNullableString(record, "description", label),
    status: readNullableEnumString(record, "status", label, TASK_STATUSES),
    priority: readNullableEnumString(record, "priority", label, TASK_PRIORITIES),
    due_at: readNullableString(record, "due_at", label),
    category: readNullableString(record, "category", label),
    conversation_id: readNullableString(record, "conversation_id", label),
    assignee_ids: readNullableStringArray(record, "assignee_ids", label),
    assignee_emails: readNullableStringArray(record, "assignee_emails", label),
    content: readNullableString(record, "content", label),
    view: readNullableEnumString(record, "view", label, TASK_VIEWS),
    scope: readNullableEnumString(record, "scope", label, TASK_SCOPES),
    due_from: readNullableString(record, "due_from", label),
    due_to: readNullableString(record, "due_to", label),
    limit: readNullableNumber(record, "limit", label),
  };
}

export function parseLoadSkillToolArguments(
  raw: unknown,
  label: string = "toolArguments.loadSkill",
): LoadSkillToolArguments {
  const record = expectRecord(raw, label);
  return {
    skill_id: readString(record, "skill_id", label),
  };
}

export function parseChartToolArguments(
  raw: unknown,
  label: string = "toolArguments.chart",
): ChartToolArguments {
  const record = expectRecord(raw, label);
  const data = record.data;
  if (!Array.isArray(data) || data.length === 0) {
    throw new Error(`${label}.data must be a non-empty array`);
  }
  return {
    type: readNullableEnumString(record, "type", label, CHART_TOOL_TYPES) ?? (() => {
      throw new Error(`${label}.type is required`);
    })(),
    title: readString(record, "title", label),
    data: data.map((entry, index) => expectRecord(entry, `${label}.data[${index}]`)),
    x_axis_key: readNullableString(record, "x_axis_key", label),
    data_keys: readNullableStringArray(record, "data_keys", label),
    x_axis_label: readNullableString(record, "x_axis_label", label),
    y_axis_label: readNullableString(record, "y_axis_label", label),
    colors: readNullableStringArray(record, "colors", label),
  };
}

export function parseGanttToolArguments(
  raw: unknown,
  label: string = "toolArguments.gantt",
): GanttToolArguments {
  const record = expectRecord(raw, label);
  const rawTasks = record.tasks;
  if (!Array.isArray(rawTasks) || rawTasks.length === 0) {
    throw new Error(`${label}.tasks must be a non-empty array`);
  }
  return {
    title: readString(record, "title", label),
    tasks: rawTasks.map((entry, index) => {
      const task = expectRecord(entry, `${label}.tasks[${index}]`);
      return {
        id: readString(task, "id", `${label}.tasks[${index}]`),
        name: readString(task, "name", `${label}.tasks[${index}]`),
        start: readString(task, "start", `${label}.tasks[${index}]`),
        end: readString(task, "end", `${label}.tasks[${index}]`),
        progress: readNullableNumber(task, "progress", `${label}.tasks[${index}]`),
        dependencies: readNullableString(task, "dependencies", `${label}.tasks[${index}]`),
        custom_bar_color: readNullableString(task, "custom_bar_color", `${label}.tasks[${index}]`),
      };
    }),
    view_mode: readNullableEnumString(record, "view_mode", label, GANTT_VIEW_MODES),
    readonly: readNullableBoolean(record, "readonly", label),
  };
}

export function parseRequestUserInputToolArguments(
  raw: unknown,
  label: string = "toolArguments.requestUserInput",
): RequestUserInputToolArguments {
  const record = expectRecord(raw, label);
  const rawQuestions = record.questions;
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) {
    throw new Error(`${label}.questions must be a non-empty array`);
  }
  return {
    title: readString(record, "title", label),
    prompt: readString(record, "prompt", label),
    questions: rawQuestions.map((entry, index) =>
      parseUserInputQuestionPayload(entry, `${label}.questions[${index}]`),
    ),
    submit_label: readNullableString(record, "submit_label", label),
  };
}

export function parseExecuteCodeToolArguments(
  raw: unknown,
  label: string = "toolArguments.executeCode",
): ExecuteCodeToolArguments {
  const record = expectRecord(raw, label);
  return {
    code: readString(record, "code", label),
    file_ids: readNullableStringArray(record, "file_ids", label),
    skill_assets: readNullableStringArray(record, "skill_assets", label),
    timeout: readNullableNumber(record, "timeout", label),
  };
}

export function parseToolArgumentsPayloadForTool(
  toolName: unknown,
  raw: unknown,
  label: string = "toolArguments",
): KnownToolArgumentsPayload {
  const schemaKind = getToolArgsSchemaKind(toolName);
  if (!schemaKind) {
    throw new Error(`${label}.toolName must be a supported tool`);
  }
  switch (schemaKind) {
    case "query":
      return parseQueryToolArguments(raw, label);
    case "retrievalProjectFiles":
      return parseRetrievalProjectFilesToolArguments(raw, label);
    case "fileRead":
      return parseFileReadToolArguments(raw, label);
    case "record":
      return expectRecord(raw, label);
    case "tasks":
      return parseTasksToolArguments(raw, label);
    case "loadSkill":
      return parseLoadSkillToolArguments(raw, label);
    case "chart":
      return parseChartToolArguments(raw, label);
    case "gantt":
      return parseGanttToolArguments(raw, label);
    case "requestUserInput":
      return parseRequestUserInputToolArguments(raw, label);
    case "executeCode":
      return parseExecuteCodeToolArguments(raw, label);
    default:
      throw new Error(`${label}.toolName must be a supported tool`);
  }
}
