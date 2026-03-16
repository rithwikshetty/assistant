
import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  type Task,
  type TaskAssignee,
  type TaskStatus,
  type TaskPriority,
  parseTaskPriority,
  parseTaskStatus,
  getTask,
  updateTask,
  createTask,
  listTaskComments,
  addTaskComment,
  searchTaskAssignees,
} from "@/lib/api/tasks";
import { PopoverSurface } from "@/components/ui/popover-surface";
import { useAuth } from "@/contexts/auth-context";

function statusLabel(status: TaskStatus): string {
  switch (status) {
    case "todo":
      return "To do";
    case "in_progress":
      return "In progress";
    case "done":
      return "Done";
  }
}

function priorityLabel(priority: TaskPriority): string {
  switch (priority) {
    case "low":
      return "Low";
    case "medium":
      return "Medium";
    case "high":
      return "High";
    case "urgent":
      return "Urgent";
  }
}

function toLocalDateInput(iso: string): string {
  const trimmed = iso?.trim?.() ?? "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    return trimmed;
  }
  try {
    const d = new Date(trimmed);
    if (Number.isNaN(d.getTime())) {
      return "";
    }
    const pad = (n: number) => String(n).padStart(2, "0");
    const yyyy = d.getFullYear();
    const mm = pad(d.getMonth() + 1);
    const dd = pad(d.getDate());
    return `${yyyy}-${mm}-${dd}`;
  } catch {
    return "";
  }
}

function AssigneePicker({
  value,
  onChange,
  disabled,
  excludedUserIds,
  onMaxReached,
}: {
  value: TaskAssignee[];
  onChange: (next: TaskAssignee[]) => void;
  disabled?: boolean;
  excludedUserIds?: string[];
  onMaxReached?: () => void;
}) {
  const [query, setQuery] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [results, setResults] = React.useState<Array<{ id: string; name?: string | null; email: string }>>([]);

  React.useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      return;
    }

    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const users = await searchTaskAssignees(q, 10);
          if (cancelled) return;
          const selectedIds = new Set(value.map((item) => item.user_id));
          const excluded = new Set((excludedUserIds ?? []).filter(Boolean));
          const filtered = users.filter((user) => !excluded.has(user.id) && !selectedIds.has(user.id));
          setResults(filtered);
        } catch {
          if (!cancelled) setResults([]);
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();
    }, 220);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, value, excludedUserIds]);

  const removeAssignee = (userId: string) => {
    onChange(value.filter((item) => item.user_id !== userId));
  };

  const addAssignee = (user: { id: string; name?: string | null; email: string }) => {
    if (value.length >= 5) {
      onMaxReached?.();
      return;
    }
    onChange([
      ...value,
      {
        user_id: user.id,
        user_name: user.name ?? user.email,
        user_email: user.email,
        assigned_by_id: "",
        seen_at: null,
      },
    ]);
    setQuery("");
    setResults([]);
  };

  const [inputFocused, setInputFocused] = React.useState(false);
  const showDropdown = inputFocused && query.trim().length > 0;

  return (
    <div className="space-y-2">
      <div className="relative rounded-md border p-2 space-y-2">
        {value.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {value.map((assignee) => {
              const label = assignee.user_name || assignee.user_email || "?";
              const initials = label.split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
              return (
                <span key={assignee.user_id} className="inline-flex items-center gap-1.5 rounded-lg bg-muted/40 pl-1 pr-2 py-0.5 type-control-compact text-foreground">
                  <span className="flex size-5 items-center justify-center rounded-full bg-primary/15 type-nav-meta text-primary shrink-0">
                    {initials}
                  </span>
                  <span className="truncate max-w-[120px]">{label}</span>
                  {!disabled && (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => removeAssignee(assignee.user_id)}
                      aria-label="Remove assignee"
                    >
                      ×
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        )}

        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setInputFocused(true)}
          onBlur={() => setTimeout(() => setInputFocused(false), 150)}
          onKeyDown={(e) => { if (e.key === "Escape") setInputFocused(false); }}
          placeholder={value.length >= 5 ? "Max 5 assignees reached" : "Type name or email to add assignee"}
          disabled={disabled || value.length >= 5}
          aria-autocomplete="list"
          aria-expanded={showDropdown && results.length > 0}
        />

        {showDropdown && (
          <PopoverSurface asChild={false} elevation="lg" className="absolute z-20 bottom-full left-0 right-0 mb-1 max-h-52 overflow-y-auto">
            {query.trim().length < 2 ? (
              <div className="px-3 py-2 type-caption text-muted-foreground">Type at least 2 characters.</div>
            ) : loading ? (
              <div className="px-3 py-2 type-caption text-muted-foreground">Searching…</div>
            ) : results.length > 0 ? (
              <div role="listbox" aria-label="Assignee suggestions">
                {results.map((user) => {
                  const userLabel = user.name || user.email;
                  const userInitials = userLabel.split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
                  return (
                    <button
                      key={user.id}
                      type="button"
                      role="option"
                      className="flex w-full items-center gap-2.5 px-3 py-2 type-body text-left hover:bg-muted/50 transition-colors"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => addAssignee(user)}
                    >
                      <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 type-control-compact text-primary shrink-0">
                        {userInitials}
                      </span>
                      <div className="min-w-0">
                        <div className="type-control truncate">{user.name || user.email}</div>
                        <div className="type-caption text-muted-foreground truncate">{user.email}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="px-3 py-2 type-caption text-muted-foreground">No matching active users.</div>
            )}
          </PopoverSurface>
        )}
      </div>
      <div className="type-caption text-muted-foreground">{value.length} / 5 assignees</div>
    </div>
  );
}

export function TaskDetailModal({
  taskId,
  onClose,
  onSaved,
  onViewed,
}: {
  taskId: string | null;
  onClose: () => void;
  onSaved?: () => void;
  onViewed?: () => void;
}) {
  const { addToast } = useToast();
  const open = Boolean(taskId);
  const onViewedRef = React.useRef(onViewed);
  React.useEffect(() => {
    onViewedRef.current = onViewed;
  }, [onViewed]);
  const [hydratedTask, setHydratedTask] = React.useState<Task | null>(null);
  const [hydrating, setHydrating] = React.useState(false);

  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [status, setStatus] = React.useState<TaskStatus>("todo");
  const [priority, setPriority] = React.useState<TaskPriority>("medium");
  const [dueAt, setDueAt] = React.useState<string>("");
  const [category, setCategory] = React.useState<string>("");
  const [assignees, setAssignees] = React.useState<TaskAssignee[]>([]);
  const [saveState, setSaveState] = React.useState<"idle" | "saving" | "saved" | "error">("idle");
  const lastSaved = React.useRef<{
    title: string;
    description: string;
    status: TaskStatus;
    priority: TaskPriority;
    dueAt: string;
    category: string;
    assigneeIds: string[];
  } | null>(null);

  React.useEffect(() => {
    if (!open || !taskId) {
      setHydratedTask(null);
      setHydrating(false);
      setSaveState("idle");
      lastSaved.current = null;
      setTitle("");
      setDescription("");
      setStatus("todo");
      setPriority("medium");
      setDueAt("");
      setCategory("");
      setAssignees([]);
      return;
    }

    let cancelled = false;
    setHydrating(true);
    (async () => {
      try {
        const fresh = await getTask(taskId);
        if (!cancelled) {
          setHydratedTask(fresh);
          onViewedRef.current?.();
        }
      } catch (e) {
        if (!cancelled) {
          addToast({ title: "Failed to load task", description: e instanceof Error ? e.message : "Please try again.", type: "error" });
          setHydratedTask(null);
        }
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, taskId, addToast]);

  React.useEffect(() => {
    if (!open || !hydratedTask) return;
    setTitle(hydratedTask.title);
    setDescription(hydratedTask.description ?? "");
    setStatus(parseTaskStatus(hydratedTask.status));
    setPriority(parseTaskPriority(hydratedTask.priority));
    setDueAt(hydratedTask.due_at ? toLocalDateInput(hydratedTask.due_at) : "");
    setCategory(hydratedTask.category ?? "");
    setAssignees(hydratedTask.assignees ?? []);
    const assigneeIds = (hydratedTask.assignees ?? []).map((a) => a.user_id).sort();
    lastSaved.current = {
      title: hydratedTask.title,
      description: hydratedTask.description ?? "",
      status: parseTaskStatus(hydratedTask.status),
      priority: parseTaskPriority(hydratedTask.priority),
      dueAt: hydratedTask.due_at ? toLocalDateInput(hydratedTask.due_at) : "",
      category: hydratedTask.category ?? "",
      assigneeIds,
    };
    setSaveState("idle");
  }, [open, hydratedTask]);

  const saveIfChanged = React.useCallback(async () => {
    const task = hydratedTask;
    if (!task) return;
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setSaveState("error");
      return;
    }

    const nextSnapshot = {
      title: trimmedTitle,
      description: description.trim(),
      status,
      priority,
      dueAt,
      category,
      assigneeIds: assignees.map((a) => a.user_id).sort(),
    };

    if (lastSaved.current) {
      const prev = lastSaved.current;
      if (
        prev.title === nextSnapshot.title &&
        prev.description === nextSnapshot.description &&
        prev.status === nextSnapshot.status &&
        prev.priority === nextSnapshot.priority &&
        prev.dueAt === nextSnapshot.dueAt &&
        prev.category === nextSnapshot.category &&
        prev.assigneeIds.join("|") === nextSnapshot.assigneeIds.join("|")
      ) {
        return;
      }
    }

    setSaveState("saving");
    try {
      const payload: {
        title: string;
        description: string | null;
        status: TaskStatus;
        priority: TaskPriority;
        due_at: string | null;
        completed_at?: string | null;
        category: string | null;
        assignee_ids: string[];
      } = {
        title: trimmedTitle,
        description: nextSnapshot.description || null,
        status,
        priority,
        due_at: dueAt || null,
        category: category || null,
        assignee_ids: nextSnapshot.assigneeIds,
      };
      const updated = await updateTask(task.id, payload);
      setHydratedTask(updated);
      lastSaved.current = nextSnapshot;
      setSaveState("saved");
      onSaved?.();
    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Could not save changes";
      addToast({ title: "Save failed", description: errorMessage, type: "error" });
      setSaveState("error");
    }
  }, [addToast, assignees, description, dueAt, hydratedTask, onSaved, priority, category, status, title]);

  React.useEffect(() => {
    if (!open || !hydratedTask) return;
    const timer = window.setTimeout(() => {
      void saveIfChanged();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [open, hydratedTask, title, description, status, priority, category, dueAt, assignees, saveIfChanged]);

  const ownerLabel = hydratedTask?.created_by_name || hydratedTask?.created_by_email;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Task"
      size="6xl"
      className="sm:!h-[88vh]"
    >
      {hydrating || !hydratedTask ? (
        <div className="space-y-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-[200px]" />
          <Skeleton className="h-[120px]" />
        </div>
      ) : (
        <div className="flex flex-col lg:flex-row gap-6 h-full">
          {/* Main content: title, description, comments */}
          <div className="flex-1 min-w-0 flex flex-col gap-5">
            <form
              onSubmit={(e) => { e.preventDefault(); void saveIfChanged(); }}
              className="flex flex-col gap-5"
            >
              <Input
                id="task-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Task title"
                disabled={hydrating}
                autoFocus
                className="!type-size-20 font-semibold border-none shadow-none px-0 focus-visible:ring-0 placeholder:text-muted-foreground/40 bg-transparent dark:bg-transparent"
              />

              <div>
                <label htmlFor="task-description" className="block type-overline mb-2">
                  Description
                </label>
                <Textarea
                  id="task-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Add more details..."
                  disabled={hydrating}
                  className="resize-y min-h-[140px]"
                  rows={8}
                  maxLength={5000}
                />
              </div>
            </form>

            <TaskComments taskId={hydratedTask.id} />
          </div>

          {/* Properties sidebar */}
          <div className="lg:w-[260px] lg:flex-shrink-0 lg:border-l lg:border-border/40 lg:pl-6 space-y-5">
            {/* Save indicator */}
            <div className="type-nav-meta text-muted-foreground text-right">
              {saveState === "saving" && <span>Saving…</span>}
              {saveState === "saved" && <span className="text-foreground/80">Saved</span>}
              {saveState === "error" && <span className="text-destructive">Save failed</span>}
            </div>

            {/* Owner */}
            {ownerLabel && (
              <div>
                <div className="type-overline mb-1.5">Owner</div>
                <div className="flex items-center gap-2">
                  {(() => {
                    const initials = ownerLabel.split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
                    return (
                      <span className="flex size-6 items-center justify-center rounded-full bg-muted/40 type-nav-meta text-muted-foreground shrink-0">
                        {initials}
                      </span>
                    );
                  })()}
                  <span className="type-body truncate">{ownerLabel}</span>
                </div>
              </div>
            )}

            {/* Status */}
            <div>
              <div className="type-overline mb-1.5">Status</div>
              {(() => {
                const allowed: TaskStatus[] = ["todo", "in_progress", "done"];
                const safeValue = allowed.includes(status) ? status : undefined;
                return (
                  <Select key={`status-${status}`} value={safeValue} onValueChange={(v) => setStatus(v as TaskStatus)} disabled={hydrating}>
                    <SelectTrigger aria-label="Task status" className="w-full">
                      <SelectValue placeholder={statusLabel(status)} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="todo">To do</SelectItem>
                      <SelectItem value="in_progress">In progress</SelectItem>
                      <SelectItem value="done">Done</SelectItem>
                    </SelectContent>
                  </Select>
                );
              })()}
            </div>

            {/* Priority */}
            <div>
              <div className="type-overline mb-1.5">Priority</div>
              {(() => {
                const allowed: TaskPriority[] = ["low", "medium", "high", "urgent"];
                const safeValue = allowed.includes(priority) ? priority : undefined;
                return (
                  <Select key={`priority-${priority}`} value={safeValue} onValueChange={(v) => setPriority(v as TaskPriority)} disabled={hydrating}>
                    <SelectTrigger aria-label="Task priority" className="w-full">
                      <SelectValue placeholder={priorityLabel(priority)} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="urgent">Urgent</SelectItem>
                    </SelectContent>
                  </Select>
                );
              })()}
            </div>

            {/* Due */}
            <div>
              <div className="type-overline mb-1.5">Due date</div>
              <DatePicker
                id="task-due"
                value={dueAt}
                onChange={setDueAt}
                disabled={hydrating}
                placeholder="No due date"
              />
            </div>

            {/* Category */}
            <div>
              <div className="type-overline mb-1.5">Category</div>
              <Input
                id="task-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="None"
                disabled={hydrating}
              />
            </div>

            {/* Assignees */}
            <div>
              <div className="type-overline mb-1.5">Assignees</div>
              <AssigneePicker
                value={assignees}
                onChange={setAssignees}
                disabled={hydrating}
                excludedUserIds={hydratedTask ? [hydratedTask.created_by_id] : []}
                onMaxReached={() =>
                  addToast({
                    title: "Max assignees reached",
                    description: "A task can have at most 5 assignees.",
                    type: "error",
                  })
                }
              />
            </div>

            {/* Timestamps */}
            <div className="space-y-1 type-nav-meta text-muted-foreground pt-3 border-t border-border/30">
              <div>Created {new Date(hydratedTask.created_at).toLocaleString()}</div>
              <div>Updated {new Date(hydratedTask.updated_at).toLocaleString()}</div>
              {hydratedTask.completed_at && <div>Completed {new Date(hydratedTask.completed_at).toLocaleString()}</div>}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function TaskComments({ taskId }: { taskId: string }) {
  const { addToast } = useToast();
  const queryClient = useQueryClient();
  const { data: comments, isLoading } = useQuery({
    queryKey: ["tasks", taskId, "comments"],
    queryFn: () => listTaskComments(taskId),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const [text, setText] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  const onSubmit = async () => {
    const body = text.trim();
    if (!body) return;
    try {
      setSubmitting(true);
      await addTaskComment(taskId, body);
      setText("");
      await queryClient.invalidateQueries({ queryKey: ["tasks", taskId, "comments"] });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not add comment";
      addToast({ title: "Comment failed", description: msg, type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-2">
      <div className="rounded-md border overflow-hidden">
        <div className="px-3 py-2 border-b type-overline text-foreground/90">Comments</div>
        <div className="flex flex-col">
          <div className="overflow-y-auto h-[30vh] px-3 py-2 space-y-2">
            {isLoading ? (
              <>
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
              </>
            ) : comments && comments.length > 0 ? (
              comments.map((c) => (
                <div key={c.id} className="rounded-md border border-border/50 bg-muted/10 p-2 space-y-1">
                  <div className="type-nav-meta text-muted-foreground flex items-center justify-between gap-2">
                    <span>{c.user_name || c.user_email || "Unknown user"}</span>
                    <span>{new Date(c.created_at).toLocaleString()}</span>
                  </div>
                  <div className="type-body leading-snug whitespace-pre-wrap break-words">{c.content}</div>
                </div>
              ))
            ) : (
              <div className="type-caption text-muted-foreground italic px-1">No comments yet.</div>
            )}
          </div>

          <div className="border-t p-2 space-y-2">
            <Textarea
              placeholder="Add a comment…"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void onSubmit();
                }
              }}
              rows={2}
              className="resize-none min-h-[56px]"
            />
            <div className="flex items-center justify-between type-nav-meta text-muted-foreground">
              <span className="hidden sm:inline">Press ⌘Enter to send</span>
              <Button size="sm" disabled={submitting || !text.trim()} onClick={onSubmit}>
                Add Comment
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function CreateTaskModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const { addToast } = useToast();
  const { user } = useAuth();
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [priority, setPriority] = React.useState<TaskPriority>("medium");
  const [dueAt, setDueAt] = React.useState<string>("");
  const [category, setCategory] = React.useState<string>("");
  const [assignees, setAssignees] = React.useState<TaskAssignee[]>([]);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setTitle("");
      setDescription("");
      setPriority("medium");
      setDueAt("");
      setCategory("");
      setAssignees([]);
      setSubmitting(false);
    }
  }, [open]);

  const canCreate = title.trim().length > 0 && !submitting;

  const onCreate = async () => {
    try {
      setSubmitting(true);
      await createTask({
        title: title.trim(),
        description: description.trim() ? description.trim() : null,
        priority,
        status: "todo",
        due_at: dueAt || null,
        category: category.trim() ? category.trim() : null,
        assignee_ids: assignees.map((a) => a.user_id),
      });
      addToast({ title: "Task created", type: "success" });
      onCreated?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Could not create task";
      addToast({ title: "Create failed", description: msg, type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New Task"
      size="3xl"
      actions={
        <Button size="sm" disabled={!canCreate} onClick={onCreate}>
          Create
        </Button>
      }
    >
      <div className="space-y-4">
        <div>
          <label htmlFor="new-task-title" className="block type-control text-foreground mb-1.5">
            Title <span className="text-destructive">*</span>
          </label>
          <Input
            id="new-task-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What do you need to do?"
            autoFocus
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="new-task-priority" className="block type-control text-foreground mb-1.5">
              Priority
            </label>
            <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
              <SelectTrigger id="new-task-priority">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="urgent">Urgent</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label htmlFor="new-task-due" className="block type-control text-foreground mb-1.5">
              Due
            </label>
            <DatePicker
              id="new-task-due"
              value={dueAt}
              onChange={setDueAt}
              placeholder="Choose a date"
            />
          </div>
        </div>

        <div>
          <label htmlFor="new-task-category" className="block type-control text-foreground mb-1.5">
            Category <span className="type-caption text-muted-foreground">(optional, free text)</span>
          </label>
          <Input
            id="new-task-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="e.g. Internal roll-out"
          />
        </div>

        <div>
          <label className="block type-control text-foreground mb-1.5">
            Assignees <span className="type-caption text-muted-foreground">(optional, max 5)</span>
          </label>
          <AssigneePicker
            value={assignees}
            onChange={setAssignees}
            disabled={submitting}
            excludedUserIds={user?.id ? [user.id] : []}
            onMaxReached={() =>
              addToast({
                title: "Max assignees reached",
                description: "A task can have at most 5 assignees.",
                type: "error",
              })
            }
          />
        </div>

        <div>
          <label htmlFor="new-task-description" className="block type-control text-foreground mb-1.5">
            Description <span className="type-caption text-muted-foreground">(optional)</span>
          </label>
          <Textarea
            id="new-task-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Add more details..."
            rows={6}
            className="resize-y min-h-[160px]"
            maxLength={5000}
          />
        </div>
      </div>
    </Modal>
  );
}
