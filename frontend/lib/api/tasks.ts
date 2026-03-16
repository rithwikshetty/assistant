import { fetchWithAuth } from "@/lib/api/auth";
import { readApiErrorMessage } from "@/lib/api/errors";
import type { ApiSchema } from "@/lib/api/generated/types";
import {
  parseTask,
  parseTaskAssignableUsers,
  parseTaskCommentsResponse,
  parseTaskList,
  parseTaskPriority,
  parseSingleTaskComment,
  parseTaskStatus,
  parseTaskUnseenCount,
  type Task,
  type TaskAssignableUser,
  type TaskComment,
  type TaskListView,
  type TaskPriority,
  type TaskScope,
  type TaskStatus,
} from "@/lib/contracts/tasks";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";

const API_BASE_URL = getBackendBaseUrl();
export type {
  Task,
  TaskAssignee,
  TaskAssignableUser,
  TaskComment,
  TaskListView,
  TaskPriority,
  TaskScope,
  TaskStatus,
} from "@/lib/contracts/tasks";
export { parseTaskPriority, parseTaskStatus };

export interface ListTasksParams {
  view?: TaskListView; // defaults to 'active' on server
  scope?: TaskScope;   // defaults to 'all' on server
  status?: TaskStatus[];
  priority?: TaskPriority[];
  due_from?: string; // YYYY-MM-DD
  due_to?: string;   // YYYY-MM-DD
  category?: string;
}

function toQuery(params?: ListTasksParams): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  if (params.view) sp.set("view", params.view);
  if (params.scope) sp.set("scope", params.scope);
  if (params.status) params.status.forEach(s => sp.append("status", s));
  if (params.priority) params.priority.forEach(p => sp.append("priority", p));
  if (params.due_from) sp.set("due_from", params.due_from);
  if (params.due_to) sp.set("due_to", params.due_to);
  if (params.category) sp.set("category", params.category);
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export async function listTasks(params?: ListTasksParams): Promise<Task[]> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks${toQuery(params)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to load tasks"));
  return parseTaskList(await res.json());
}

export async function getTask(taskId: string): Promise<Task> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/${taskId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to load task"));
  return parseTask(await res.json());
}

export async function listTaskComments(taskId: string): Promise<TaskComment[]> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/${taskId}/comments`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to load comments"));
  return parseTaskCommentsResponse(await res.json());
}

export async function addTaskComment(taskId: string, content: string): Promise<TaskComment> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/${taskId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to add comment"));
  return parseSingleTaskComment(await res.json());
}

export type CreateTaskPayload = ApiSchema<"TaskCreate">;

export async function createTask(payload: CreateTaskPayload): Promise<Task> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to create task"));
  return parseTask(await res.json());
}

export type UpdateTaskPayload = ApiSchema<"TaskUpdate">;

export async function updateTask(taskId: string, payload: UpdateTaskPayload): Promise<Task> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to update task"));
  return parseTask(await res.json());
}

export async function completeTask(taskId: string): Promise<Task> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/${taskId}/complete`, { method: "POST" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to complete task"));
  return parseTask(await res.json());
}

export async function deleteTask(taskId: string): Promise<Task> {
  // Soft delete via archive endpoint
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/${taskId}/archive?archive=true`, { method: "POST" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to delete task"));
  return parseTask(await res.json());
}

// Hard delete removed; prefer deleteTask(taskId) which soft-deletes

export async function searchTaskAssignees(q: string, limit = 10): Promise<TaskAssignableUser[]> {
  const sp = new URLSearchParams();
  sp.set("q", q);
  sp.set("limit", String(limit));
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/assignees/search?${sp.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to search assignees"));
  return parseTaskAssignableUsers(await res.json());
}

export async function getUnseenAssignedTaskCount(): Promise<number> {
  const res = await fetchWithAuth(`${API_BASE_URL}/tasks/unseen-count`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readApiErrorMessage(res, "Failed to load unseen task count"));
  return parseTaskUnseenCount(await res.json());
}
