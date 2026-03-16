import {
  expectRecord,
  readString,
  readNullableString,
  readBoolean,
} from "./contract-utils";

export type TaskStatus = "todo" | "in_progress" | "done";
export type TaskPriority = "low" | "medium" | "high" | "urgent";
export type TaskScope = "all" | "created" | "assigned";
export type TaskListView = "active" | "completed" | "all";

export interface TaskAssignee {
  user_id: string;
  user_name?: string | null;
  user_email?: string | null;
  assigned_by_id: string;
  seen_at?: string | null;
}

export interface Task {
  id: string;
  created_by_id: string;
  created_by_name?: string | null;
  created_by_email?: string | null;
  category?: string | null;
  conversation_id?: string | null;
  title: string;
  description?: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  due_at?: string | null;
  completed_at?: string | null;
  is_archived: boolean;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
  assignees: TaskAssignee[];
  is_assigned_to_me: boolean;
  is_unseen_for_me: boolean;
}

export interface TaskComment {
  id: string;
  task_id: string;
  user_id: string;
  user_name?: string | null;
  user_email?: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface TaskAssignableUser {
  id: string;
  name?: string | null;
  email: string;
}

export function parseTaskStatus(value: unknown): TaskStatus {
  if (value === "todo" || value === "in_progress" || value === "done") {
    return value;
  }
  throw new Error("task.status must be one of: todo, in_progress, done");
}

export function parseTaskPriority(value: unknown): TaskPriority {
  if (value === "low" || value === "medium" || value === "high" || value === "urgent") {
    return value;
  }
  throw new Error("task.priority must be one of: low, medium, high, urgent");
}

function parseTaskAssignee(value: unknown, label: string): TaskAssignee {
  const record = expectRecord(value, label);
  return {
    user_id: readString(record, "user_id", label),
    user_name: readNullableString(record, "user_name", label),
    user_email: readNullableString(record, "user_email", label),
    assigned_by_id: readString(record, "assigned_by_id", label),
    seen_at: readNullableString(record, "seen_at", label),
  };
}

export function parseTask(value: unknown): Task {
  const record = expectRecord(value, "task");
  const assigneesRaw = record.assignees;
  if (!Array.isArray(assigneesRaw)) {
    throw new Error("task.assignees must be an array");
  }
  return {
    id: readString(record, "id", "task"),
    created_by_id: readString(record, "created_by_id", "task"),
    created_by_name: readNullableString(record, "created_by_name", "task"),
    created_by_email: readNullableString(record, "created_by_email", "task"),
    category: readNullableString(record, "category", "task"),
    conversation_id: readNullableString(record, "conversation_id", "task"),
    title: readString(record, "title", "task"),
    description: readNullableString(record, "description", "task"),
    status: parseTaskStatus(record.status),
    priority: parseTaskPriority(record.priority),
    due_at: readNullableString(record, "due_at", "task"),
    completed_at: readNullableString(record, "completed_at", "task"),
    is_archived: readBoolean(record, "is_archived", "task"),
    archived_at: readNullableString(record, "archived_at", "task"),
    created_at: readString(record, "created_at", "task"),
    updated_at: readString(record, "updated_at", "task"),
    assignees: assigneesRaw.map((item, index) => parseTaskAssignee(item, `task.assignees[${index}]`)),
    is_assigned_to_me: readBoolean(record, "is_assigned_to_me", "task"),
    is_unseen_for_me: readBoolean(record, "is_unseen_for_me", "task"),
  };
}

export function parseTaskList(value: unknown): Task[] {
  if (!Array.isArray(value)) {
    throw new Error("tasks must be an array");
  }
  return value.map((item) => parseTask(item));
}

function parseTaskComment(value: unknown, label: string): TaskComment {
  const record = expectRecord(value, label);
  return {
    id: readString(record, "id", label),
    task_id: readString(record, "task_id", label),
    user_id: readString(record, "user_id", label),
    user_name: readNullableString(record, "user_name", label),
    user_email: readNullableString(record, "user_email", label),
    content: readString(record, "content", label),
    created_at: readString(record, "created_at", label),
    updated_at: readString(record, "updated_at", label),
  };
}

export function parseSingleTaskComment(value: unknown): TaskComment {
  return parseTaskComment(value, "taskComment");
}

export function parseTaskCommentsResponse(value: unknown): TaskComment[] {
  const record = expectRecord(value, "taskComments");
  const items = record.items;
  if (!Array.isArray(items)) {
    throw new Error("taskComments.items must be an array");
  }
  return items.map((item, index) => parseTaskComment(item, `taskComments.items[${index}]`));
}

export function parseTaskAssignableUsers(value: unknown): TaskAssignableUser[] {
  if (!Array.isArray(value)) {
    throw new Error("taskAssignableUsers must be an array");
  }
  return value.map((item, index) => {
    const record = expectRecord(item, `taskAssignableUsers[${index}]`);
    return {
      id: readString(record, "id", `taskAssignableUsers[${index}]`),
      name: readNullableString(record, "name", `taskAssignableUsers[${index}]`),
      email: readString(record, "email", `taskAssignableUsers[${index}]`),
    };
  });
}

export function parseTaskUnseenCount(value: unknown): number {
  const record = expectRecord(value, "taskUnseenCount");
  const raw = record.count;
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    throw new Error("taskUnseenCount.count must be numeric");
  }
  return Math.max(0, Math.floor(raw));
}
