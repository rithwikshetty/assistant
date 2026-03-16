import {
  type JsonRecord,
  expectRecord,
  readString,
  readNullableString,
  readNullableBoolean,
  readNullableNumber,
  readNullableStringArray,
  readNullableRecord,
  readRecordArray,
} from "./contract-utils";

export interface WebSearchCitationPayload {
  index?: number | null;
  url: string;
  title?: string | null;
  snippet?: string | null;
  published_at?: string | null;
  updated_at?: string | null;
}

export interface WebSearchResultPayload {
  content: string;
  citations: WebSearchCitationPayload[];
}

export interface KnowledgeSourcePayload {
  content?: string | null;
  score?: number | null;
  metadata?: JsonRecord | null;
}

export interface KnowledgeProjectFileResultPayload {
  file_id?: string | null;
  filename?: string | null;
  excerpts?: string[] | null;
  file_type?: string | null;
  file_size?: number | null;
  match_count?: number | null;
  filename_match?: boolean | null;
}

export interface KnowledgeResultPayload {
  content?: string | null;
  message?: string | null;
  sources?: KnowledgeSourcePayload[] | null;
  files?: string[] | null;
  results?: KnowledgeProjectFileResultPayload[] | null;
  total_nodes?: number | null;
  query?: string | null;
  error?: string | null;
}

export interface CalculationInputPayload {
  label?: string | null;
  value?: number | null;
  display?: string | null;
}

export interface CalculationValuePayload {
  label?: string | null;
  value?: number | null;
  display?: string | null;
}

export interface CalculationDetailPayload {
  label?: string | null;
  value?: string | null;
}

export interface CalculationResultPayload {
  operation?: string | null;
  operation_label?: string | null;
  precision?: number | null;
  inputs?: Record<string, CalculationInputPayload> | null;
  result?: CalculationValuePayload | null;
  explanation?: string | null;
  reasoning?: string | null;
  details?: CalculationDetailPayload[] | null;
  error?: string | null;
}

export interface TaskAssigneePayload {
  user_id?: string | null;
  user_name?: string | null;
  user_email?: string | null;
  assigned_by_id?: string | null;
  seen_at?: string | null;
}

export interface TaskItemPayload {
  id?: string | null;
  created_by_id?: string | null;
  category?: string | null;
  conversation_id?: string | null;
  title?: string | null;
  description?: string | null;
  status?: string | null;
  priority?: string | null;
  due_at?: string | null;
  completed_at?: string | null;
  is_archived?: boolean | null;
  archived_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  assignees?: TaskAssigneePayload[] | null;
  is_assigned_to_me?: boolean | null;
  is_unseen_for_me?: boolean | null;
}

export interface TaskCommentPayload {
  id?: string | null;
  task_id?: string | null;
  user_id?: string | null;
  user_name?: string | null;
  user_email?: string | null;
  content?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TasksResultPayload {
  action?: string | null;
  task?: TaskItemPayload | null;
  items?: TaskItemPayload[] | null;
  count?: number | null;
  comment?: TaskCommentPayload | null;
  comments?: TaskCommentPayload[] | null;
  message?: string | null;
  query?: string | null;
  results?: KnowledgeProjectFileResultPayload[] | null;
  error?: string | null;
}

export type GroupedToolResultPayload =
  | WebSearchResultPayload
  | KnowledgeResultPayload
  | CalculationResultPayload
  | TasksResultPayload;

function parseTaskAssigneePayload(raw: unknown, label: string): TaskAssigneePayload {
  const record = expectRecord(raw, label);
  return {
    user_id: readNullableString(record, "user_id"),
    user_name: readNullableString(record, "user_name"),
    user_email: readNullableString(record, "user_email"),
    assigned_by_id: readNullableString(record, "assigned_by_id"),
    seen_at: readNullableString(record, "seen_at"),
  };
}

function parseTaskItemPayload(raw: unknown, label: string): TaskItemPayload {
  const record = expectRecord(raw, label);
  return {
    id: readNullableString(record, "id"),
    created_by_id: readNullableString(record, "created_by_id"),
    category: readNullableString(record, "category"),
    conversation_id: readNullableString(record, "conversation_id"),
    title: readNullableString(record, "title"),
    description: readNullableString(record, "description"),
    status: readNullableString(record, "status"),
    priority: readNullableString(record, "priority"),
    due_at: readNullableString(record, "due_at"),
    completed_at: readNullableString(record, "completed_at"),
    is_archived: readNullableBoolean(record, "is_archived"),
    archived_at: readNullableString(record, "archived_at"),
    created_at: readNullableString(record, "created_at"),
    updated_at: readNullableString(record, "updated_at"),
    assignees: (() => {
      if (!("assignees" in record)) return undefined;
      const rawAssignees = record.assignees;
      if (rawAssignees == null) return null;
      if (!Array.isArray(rawAssignees)) {
        throw new Error(`${label}.assignees must be an array or null`);
      }
      return rawAssignees.map((entry, index) => parseTaskAssigneePayload(entry, `${label}.assignees[${index}]`));
    })(),
    is_assigned_to_me: readNullableBoolean(record, "is_assigned_to_me"),
    is_unseen_for_me: readNullableBoolean(record, "is_unseen_for_me"),
  };
}

function parseTaskCommentPayload(raw: unknown, label: string): TaskCommentPayload {
  const record = expectRecord(raw, label);
  return {
    id: readNullableString(record, "id"),
    task_id: readNullableString(record, "task_id"),
    user_id: readNullableString(record, "user_id"),
    user_name: readNullableString(record, "user_name"),
    user_email: readNullableString(record, "user_email"),
    content: readNullableString(record, "content"),
    created_at: readNullableString(record, "created_at"),
    updated_at: readNullableString(record, "updated_at"),
  };
}

export function parseWebSearchResultPayload(
  raw: unknown,
  label: string = "webSearchResult",
): WebSearchResultPayload {
  const record = expectRecord(raw, label);
  return {
    content: readString(record, "content", label),
    citations: readRecordArray(record, "citations", label).map((citation, index) => ({
      index: readNullableNumber(citation, "index"),
      url: readString(citation, "url", `${label}.citations[${index}]`),
      title: readNullableString(citation, "title"),
      snippet: readNullableString(citation, "snippet"),
      published_at: readNullableString(citation, "published_at"),
      updated_at: readNullableString(citation, "updated_at"),
    })),
  };
}

export function parseKnowledgeResultPayload(
  raw: unknown,
  label: string = "knowledgeResult",
): KnowledgeResultPayload {
  const record = expectRecord(raw, label);
  return {
    content: readNullableString(record, "content"),
    message: readNullableString(record, "message"),
    sources: (() => {
      if (!("sources" in record)) return undefined;
      const rawSources = record.sources;
      if (rawSources == null) return null;
      if (!Array.isArray(rawSources)) {
        throw new Error(`${label}.sources must be an array or null`);
      }
      return rawSources.map((entry, index) => {
        const source = expectRecord(entry, `${label}.sources[${index}]`);
        return {
          content: readNullableString(source, "content"),
          score: readNullableNumber(source, "score"),
          metadata: readNullableRecord(source, "metadata"),
        };
      });
    })(),
    files: readNullableStringArray(record, "files"),
    results: (() => {
      if (!("results" in record)) return undefined;
      const rawResults = record.results;
      if (rawResults == null) return null;
      if (!Array.isArray(rawResults)) {
        throw new Error(`${label}.results must be an array or null`);
      }
      return rawResults.map((entry, index) => {
        const item = expectRecord(entry, `${label}.results[${index}]`);
        return {
          file_id: readNullableString(item, "file_id"),
          filename: readNullableString(item, "filename"),
          excerpts: readNullableStringArray(item, "excerpts"),
          file_type: readNullableString(item, "file_type"),
          file_size: readNullableNumber(item, "file_size"),
          match_count: readNullableNumber(item, "match_count"),
          filename_match: readNullableBoolean(item, "filename_match"),
        };
      });
    })(),
    total_nodes: readNullableNumber(record, "total_nodes"),
    query: readNullableString(record, "query"),
    error: readNullableString(record, "error"),
  };
}

export function parseCalculationResultPayload(
  raw: unknown,
  label: string = "calculationResult",
): CalculationResultPayload {
  const record = expectRecord(raw, label);
  const inputsRaw = readNullableRecord(record, "inputs");
  return {
    operation: readNullableString(record, "operation"),
    operation_label: readNullableString(record, "operation_label"),
    precision: readNullableNumber(record, "precision"),
    inputs: inputsRaw
      ? Object.fromEntries(
          Object.entries(inputsRaw).map(([key, value]) => {
            const input = expectRecord(value, `${label}.inputs.${key}`);
            return [key, {
              label: readNullableString(input, "label"),
              value: readNullableNumber(input, "value"),
              display: readNullableString(input, "display"),
            }];
          }),
        )
      : inputsRaw,
    result: (() => {
      const resultValue = readNullableRecord(record, "result");
      if (!resultValue) return resultValue;
      return {
        label: readNullableString(resultValue, "label"),
        value: readNullableNumber(resultValue, "value"),
        display: readNullableString(resultValue, "display"),
      };
    })(),
    explanation: readNullableString(record, "explanation"),
    reasoning: readNullableString(record, "reasoning"),
    details: (() => {
      if (!("details" in record)) return undefined;
      const rawDetails = record.details;
      if (rawDetails == null) return null;
      if (!Array.isArray(rawDetails)) {
        throw new Error(`${label}.details must be an array or null`);
      }
      return rawDetails.map((entry, index) => {
        const detail = expectRecord(entry, `${label}.details[${index}]`);
        return {
          label: readNullableString(detail, "label"),
          value: readNullableString(detail, "value"),
        };
      });
    })(),
    error: readNullableString(record, "error"),
  };
}

export function parseTasksResultPayload(
  raw: unknown,
  label: string = "tasksResult",
): TasksResultPayload {
  const record = expectRecord(raw, label);
  return {
    action: readNullableString(record, "action"),
    task: (() => {
      const task = readNullableRecord(record, "task");
      return task ? parseTaskItemPayload(task, `${label}.task`) : task;
    })(),
    items: (() => {
      if (!("items" in record)) return undefined;
      const rawItems = record.items;
      if (rawItems == null) return null;
      if (!Array.isArray(rawItems)) {
        throw new Error(`${label}.items must be an array or null`);
      }
      return rawItems.map((entry, index) => parseTaskItemPayload(entry, `${label}.items[${index}]`));
    })(),
    count: readNullableNumber(record, "count"),
    comment: (() => {
      const comment = readNullableRecord(record, "comment");
      return comment ? parseTaskCommentPayload(comment, `${label}.comment`) : comment;
    })(),
    comments: (() => {
      if (!("comments" in record)) return undefined;
      const rawComments = record.comments;
      if (rawComments == null) return null;
      if (!Array.isArray(rawComments)) {
        throw new Error(`${label}.comments must be an array or null`);
      }
      return rawComments.map((entry, index) => parseTaskCommentPayload(entry, `${label}.comments[${index}]`));
    })(),
    message: readNullableString(record, "message"),
    query: readNullableString(record, "query"),
    results: (() => {
      if (!("results" in record)) return undefined;
      const rawResults = record.results;
      if (rawResults == null) return null;
      if (!Array.isArray(rawResults)) {
        throw new Error(`${label}.results must be an array or null`);
      }
      return rawResults.map((entry, index) => {
        const item = expectRecord(entry, `${label}.results[${index}]`);
        return {
          file_id: readNullableString(item, "file_id"),
          filename: readNullableString(item, "filename"),
          excerpts: readNullableStringArray(item, "excerpts"),
          file_type: readNullableString(item, "file_type"),
          file_size: readNullableNumber(item, "file_size"),
          match_count: readNullableNumber(item, "match_count"),
          filename_match: readNullableBoolean(item, "filename_match"),
        };
      });
    })(),
    error: readNullableString(record, "error"),
  };
}
