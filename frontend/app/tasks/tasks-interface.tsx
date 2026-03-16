
import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Popover from "@radix-ui/react-popover";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useIsMobile } from "@/hooks/use-mobile";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useNavigate } from "react-router-dom";
import { CheckCircle, Circle, Plus, Trash, CalendarBlank, Briefcase, WarningCircle, ArrowsDownUp, ArrowUp, ArrowDown, X, MagnifyingGlass } from "@phosphor-icons/react";
import {
  type Task,
  type TaskStatus,
  type TaskPriority,
  type TaskScope,
  listTasks,
  completeTask,
  updateTask,
  deleteTask,
  getUnseenAssignedTaskCount,
} from "@/lib/api/tasks";
import { dateOnlyToEpochMs, parseBackendDateOnly } from "@/lib/datetime";
import { TaskDetailModal, CreateTaskModal } from "@/components/tasks/task-modals";
import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { DateRangePicker, TASK_DUE_DATE_PRESETS } from "@/components/ui/date-range-picker";

type SortField = "title" | "category" | "status" | "priority" | "due_at";
type SortDir = "asc" | "desc";

type Filter = {
  status: "open" | "done" | "all";
  scope: TaskScope;
  priority: "all" | TaskPriority;
  taskStatus: "all" | TaskStatus; // granular status filter
  category: string; // "" means all categories
  q: string;
  dueFrom: string; // YYYY-MM-DD or ""
  dueTo: string;   // YYYY-MM-DD or ""
};

// Priority order for sorting (higher = more urgent)
const PRIORITY_ORDER: Record<TaskPriority, number> = { low: 0, medium: 1, high: 2, urgent: 3 };
const STATUS_ORDER: Record<TaskStatus, number> = { todo: 0, in_progress: 1, done: 2 };

export function TasksInterface() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { addToast } = useToast();
  const queryClient = useQueryClient();
  const [filter, setFilter] = React.useState<Filter>({ status: "open", scope: "all", priority: "all", taskStatus: "all", category: "", q: "", dueFrom: "", dueTo: "" });
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [sort, setSort] = React.useState<{ field: SortField; dir: SortDir }>({ field: "due_at", dir: "asc" });

  const closeTasks = () => {
    try {
      if (typeof window !== "undefined" && window.history.length > 1) {
        navigate(-1);
      } else {
        navigate("/");
      }
    } catch {
      navigate("/");
    }
  };

  const viewForQuery: "active" | "completed" | "all" = React.useMemo(() => {
    if (filter.status === "done") return "completed";
    if (filter.status === "open") return "active";
    return "all";
  }, [filter.status]);

  const queryKey = React.useMemo(
    () => ["tasks", viewForQuery, filter.scope, filter.priority, filter.taskStatus, filter.category, filter.dueFrom, filter.dueTo],
    [viewForQuery, filter.scope, filter.priority, filter.taskStatus, filter.category, filter.dueFrom, filter.dueTo]
  );

  const { data: tasks, isLoading, refetch } = useQuery<Task[]>({
    queryKey,
    queryFn: () => listTasks({
      view: viewForQuery,
      scope: filter.scope,
      priority: filter.priority === "all" ? undefined : [filter.priority],
      status: filter.taskStatus === "all" ? undefined : [filter.taskStatus],
      category: filter.category || undefined,
      due_from: filter.dueFrom || undefined,
      due_to: filter.dueTo || undefined,
    }),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    refetchOnWindowFocus: false,
  });

  const { data: unseenCount = 0 } = useQuery<number>({
    queryKey: ["tasks-unseen-count"],
    queryFn: getUnseenAssignedTaskCount,
    staleTime: 20_000,
    refetchOnWindowFocus: false,
  });

  // Maintain a stable list of all seen projects for the dropdown
  // We accumulate projects as we see them so filtering by project doesn't hide other options
  const seenCategoriesRef = React.useRef<Set<string>>(new Set());

  const uniqueCategories = React.useMemo(() => {
    (tasks ?? []).forEach((t) => {
      if (t.category) seenCategoriesRef.current.add(t.category);
    });
    return Array.from(seenCategoriesRef.current).sort((a, b) => a.localeCompare(b));
  }, [tasks]);

  const filtered = React.useMemo(() => {
    let list = tasks ?? [];
    const q = filter.q.trim().toLowerCase();
    if (q) list = list.filter((t) => t.title.toLowerCase().includes(q));
    return list;
  }, [tasks, filter.q]);

  // Sort the filtered list
  const sorted = React.useMemo(() => {
    const arr = [...filtered];
    const { field, dir } = sort;
    const mult = dir === "asc" ? 1 : -1;

    arr.sort((a, b) => {
      let cmp = 0;
      switch (field) {
        case "title":
          cmp = a.title.localeCompare(b.title);
          break;
        case "category":
          cmp = (a.category ?? "").localeCompare(b.category ?? "");
          break;
        case "status":
          cmp = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
          break;
        case "priority":
          cmp = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
          break;
        case "due_at":
          // Tasks without due dates go to end
          if (!a.due_at && !b.due_at) cmp = 0;
          else if (!a.due_at) cmp = 1;
          else if (!b.due_at) cmp = -1;
          else {
            const aTime = dateOnlyToEpochMs(a.due_at);
            const bTime = dateOnlyToEpochMs(b.due_at);
            cmp = (Number.isFinite(aTime) ? aTime : 0) - (Number.isFinite(bTime) ? bTime : 0);
          }
          break;
      }
      return cmp * mult;
    });
    return arr;
  }, [filtered, sort]);

  const toggleSort = (field: SortField) => {
    setSort((s) => s.field === field ? { field, dir: s.dir === "asc" ? "desc" : "asc" } : { field, dir: "asc" });
  };

  const onToggleComplete = async (task: Task) => {
    try {
      const next = task.status !== "done"
        ? await completeTask(task.id)
        : await updateTask(task.id, { status: "todo", completed_at: null });

      // Optimistic update
      queryClient.setQueryData<Task[]>(queryKey, (prev) => {
        if (!prev) return prev;
        const isNowDone = next.status === "done";
        if (viewForQuery === "active" && isNowDone) return prev.filter((t) => t.id !== task.id);
        if (viewForQuery === "completed" && !isNowDone) return prev.filter((t) => t.id !== task.id);
        return prev.map((t) => (t.id === task.id ? next : t));
      });

      await refetch();
      // Invalidate other task queries (e.g., if viewing "active" and task moved to "done")
      queryClient.invalidateQueries({ queryKey: ["tasks"], predicate: (query) => query.queryKey[1] !== viewForQuery });
      queryClient.invalidateQueries({ queryKey: ["tasks-unseen-count"] });
      if (selectedTaskId === task.id) setSelectedTaskId(task.id);
    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Could not update task";
      addToast({ title: "Failed to update", description: errorMessage, type: "error" });
    }
  };

  const onDeleteTask = async (task: Task) => {
    try {
      await deleteTask(task.id);
      // Optimistic update
      queryClient.setQueryData<Task[]>(queryKey, (prev) => (prev ? prev.filter((t) => t.id !== task.id) : prev));
      await refetch();
      // Invalidate other task queries
      queryClient.invalidateQueries({ queryKey: ["tasks"], predicate: (query) => query.queryKey[1] !== viewForQuery });
      queryClient.invalidateQueries({ queryKey: ["tasks-unseen-count"] });
      addToast({ title: "Task deleted", type: "success" });
      if (selectedTaskId === task.id) setSelectedTaskId(null);
    } catch (e: unknown) {
      const errorMessage = e instanceof Error ? e.message : "Could not delete task";
      addToast({ title: "Failed to delete", description: errorMessage, type: "error" });
    }
  };

  const content = (
    <>
      {/* Header */}
      <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-2 px-4 sm:px-8 bg-background/90 backdrop-blur-md border-b border-border/30">
        <div className="flex items-center gap-3">
          {isMobile && <SidebarTrigger className="-ml-2" />}
          <div className="flex items-center gap-2">
            <h1 className="type-page-title">Tasks</h1>
            {unseenCount > 0 && (
              <Badge variant="outline" className="rounded-lg border-primary/30 bg-primary/10 text-primary">
                {unseenCount} New
              </Badge>
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={closeTasks}
          aria-label="Close tasks"
          className="rounded-lg hover:bg-foreground/5 text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-5 w-5" />
        </Button>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-8 sm:py-12 flex flex-col gap-8">

            {/* Filters */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 p-1 rounded-xl bg-muted/20 border border-border/5 w-fit">
                {(([
                  { key: "open", label: "Active" },
                  { key: "done", label: "Completed" },
                  { key: "all", label: "All" },
                ] as const)).map((tab) => (
                  <Button
                    key={tab.key}
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setFilter((f) => ({ ...f, status: tab.key }))}
                    className={cn(
                      "px-4 py-1.5 rounded-lg transition-all duration-200 whitespace-nowrap type-control",
                      filter.status === tab.key
                        ? "bg-background shadow-sm text-foreground ring-1 ring-black/5 dark:ring-white/10"
                        : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                    )}
                  >
                    {tab.label}
                  </Button>
                ))}
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                <FiltersPopover
                  filter={filter}
                  setFilter={setFilter}
                  uniqueCategories={uniqueCategories}
                />

                <SearchInput
                  value={filter.q}
                  onChange={(v) => setFilter((f) => ({ ...f, q: v }))}
                  placeholder="Search tasks..."
                  containerClassName="w-full sm:w-[200px]"
                />

                <Button
                  className="rounded-lg shadow-none"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="mr-2 size-4" /> New Task
                </Button>
              </div>
            </div>

            {/* Desktop Table Layout */}
            <div className="hidden sm:block rounded-lg border border-border/40 bg-background/50 overflow-hidden">
              <Table>
                <TableHeader className="bg-transparent">
                  <TableRow className="border-b border-border/40 hover:bg-transparent">
                    <TableHead className="w-[48px]"></TableHead>
                    <SortableHeader field="title" label="Title" sort={sort} onSort={toggleSort} className="max-w-[300px]" />
                    <SortableHeader field="category" label="Category" sort={sort} onSort={toggleSort} className="w-[180px]" />
                    <SortableHeader field="status" label="Status" sort={sort} onSort={toggleSort} className="w-[130px]" />
                    <SortableHeader field="priority" label="Priority" sort={sort} onSort={toggleSort} className="w-[130px]" />
                    <TableHead className="w-[170px] type-overline">
                      <span className="normal-case text-muted-foreground type-body">Owner</span>
                    </TableHead>
                    <SortableHeader field="due_at" label="Due Date" sort={sort} onSort={toggleSort} className="w-[120px]" />
                    <TableHead className="w-[48px]"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading && Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={i} className="border-b border-border/40">
                      <TableCell colSpan={8}>
                         <div className="h-8 w-full animate-pulse bg-muted/10 rounded-md" />
                      </TableCell>
                    </TableRow>
                  ))}

                  {!isLoading && sorted.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={8} className="h-64 text-center">
                        <div className="flex flex-col items-center justify-center">
                          <div className="rounded-xl bg-muted/20 p-6 mb-4">
                            <MagnifyingGlass className="size-8 text-muted-foreground/50" />
                          </div>
                          <h3 className="type-card-title mb-1">No tasks found</h3>
                          <p className="type-body-muted max-w-xs mx-auto">
                            {filter.status !== "open" || filter.scope !== "all" || filter.priority !== "all" || filter.taskStatus !== "all" || filter.category || filter.q || filter.dueFrom || filter.dueTo
                              ? "Try adjusting your filters to see more tasks."
                              : "Get started by creating your first task."}
                          </p>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}

                  {sorted.map((task) => {
                    const isDone = task.status === "done";
                    return (
                      <TableRow
                        key={task.id}
                        className={cn(
                          "group border-b border-border/40 cursor-pointer transition-colors",
                          task.is_unseen_for_me
                            ? "bg-primary/[0.04] hover:bg-primary/[0.08]"
                            : "hover:bg-muted/30"
                        )}
                        onClick={() => setSelectedTaskId(task.id)}
                      >
                        <TableCell className={cn("w-[48px] text-center p-2", task.is_unseen_for_me && "border-l-[3px] border-l-primary/60")}>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={(e) => {
                              e.stopPropagation();
                              onToggleComplete(task);
                            }}
                            className={cn(
                              "rounded-full size-8 transition-all duration-200 hover:scale-110",
                              isDone ? "text-emerald-600 bg-emerald-500/10" : "text-muted-foreground hover:text-primary hover:bg-primary/10"
                            )}
                          >
                            {isDone ? <CheckCircle className="size-5" /> : <Circle className="size-5" />}
                          </Button>
                        </TableCell>
                        
                        <TableCell className="font-medium max-w-[300px]">
                          <div className="flex items-center gap-2 min-w-0">
                            {task.is_unseen_for_me && (
                              <span className="size-2 rounded-full bg-primary shrink-0" />
                            )}
                            <span className={cn(
                              "transition-colors text-foreground truncate",
                              isDone && "text-muted-foreground line-through decoration-border/50"
                            )}>
                              {task.title}
                            </span>
                          </div>
                        </TableCell>

                        <TableCell className="w-[180px]">
                          {task.category ? (
                            <span className="flex items-center gap-1.5 type-caption px-2 py-1 rounded-md bg-muted/30 w-fit max-w-[180px]">
                              <Briefcase className="size-3 shrink-0" />
                              <span className="truncate">{task.category}</span>
                            </span>
                          ) : (
                            <span className="type-caption text-muted-foreground/40">—</span>
                          )}
                        </TableCell>

                        <TableCell className="w-[130px]">
                          <StatusBadge status={task.status} />
                        </TableCell>

                        <TableCell className="w-[130px]">
                          <PriorityBadge priority={task.priority} />
                        </TableCell>

                        <TableCell className="w-[170px]">
                          {(() => {
                            const ownerLabel = task.created_by_name || task.created_by_email;
                            if (!ownerLabel) return <span className="type-caption text-muted-foreground/40">&mdash;</span>;
                            const initials = ownerLabel.split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
                            return (
                              <span className="flex items-center gap-1.5" title={ownerLabel}>
                                <span className="flex size-6 items-center justify-center rounded-full bg-muted/40 type-nav-meta text-muted-foreground ring-2 ring-background shrink-0">
                                  {initials}
                                </span>
                                <span className="type-caption truncate max-w-[120px]">{task.created_by_name || task.created_by_email}</span>
                              </span>
                            );
                          })()}
                        </TableCell>

                        <TableCell className="w-[120px] type-caption">
                          {task.due_at ? (
                            <span className={cn(
                              "flex items-center gap-1.5",
                              isDueDateOverdue(task.due_at) && !isDone && "text-rose-500 font-medium"
                            )}>
                              <CalendarBlank className="size-3.5" />
                              {formatDateOnly(task.due_at)}
                            </span>
                          ) : (
                            "—"
                          )}
                        </TableCell>

                        <TableCell className="w-[48px] text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteTask(task);
                            }}
                            className="size-8 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all duration-200 opacity-0 group-hover:opacity-100"
                            title="Delete task"
                          >
                            <Trash className="size-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            {/* Mobile List Layout (unchanged structure, just ensuring consistency) */}
            <div className="flex flex-col gap-2 sm:hidden">
              {/* ... Mobile content logic same as before ... */}
              {!isLoading && sorted.length === 0 && (
                 <div className="flex flex-col items-center justify-center py-12 text-center">
                    <MagnifyingGlass className="size-8 text-muted-foreground/50 mb-2" />
                    <h3 className="type-card-title">No tasks</h3>
                 </div>
              )}
              {sorted.map((task) => {
                 const isDone = task.status === "done";
                 return (
                    <div
                      key={task.id}
                      onClick={() => setSelectedTaskId(task.id)}
                      className={cn(
                        "relative rounded-lg border border-border/40 bg-background/50 p-4 shadow-sm",
                        task.is_unseen_for_me && "border-l-[3px] border-l-primary/60 bg-primary/[0.04]"
                      )}
                    >
                       <div className="flex gap-3">
                          <div className="pt-0.5">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={(e) => {
                                e.stopPropagation();
                                onToggleComplete(task);
                              }}
                              className={cn(
                                "rounded-full size-8",
                                isDone ? "text-emerald-600 bg-emerald-500/10" : "text-muted-foreground"
                              )}
                            >
                              {isDone ? <CheckCircle className="size-5" /> : <Circle className="size-5" />}
                            </Button>
                          </div>
                          <div className="flex-1 min-w-0 space-y-2">
                             <div className="flex items-center gap-2 min-w-0">
                               {task.is_unseen_for_me && (
                                 <span className="size-2 rounded-full bg-primary shrink-0" />
                               )}
                               <div className={cn("type-body font-medium truncate", isDone && "line-through text-muted-foreground")}>{task.title}</div>
                             </div>
                             <div className="flex flex-wrap gap-2">
                                <PriorityBadge priority={task.priority} />
                                {task.due_at && <span className="type-caption flex items-center gap-1"><CalendarBlank className="size-3" />{formatDateOnly(task.due_at)}</span>}
                             </div>
                             {task.assignees.length > 0 && (
                               <div className="flex flex-wrap gap-1">
                                 {task.assignees.map((assignee) => {
                                   const label = assignee.user_name || assignee.user_email || "?";
                                   const initials = label.split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
                                   return (
                                     <span key={assignee.user_id} className="inline-flex items-center gap-1 type-nav-meta pl-0.5 pr-1.5 py-0.5 rounded-lg bg-muted/40 text-muted-foreground">
                                       <span className="flex size-4 items-center justify-center rounded-full bg-primary/15 type-nav-meta text-primary shrink-0">
                                         {initials}
                                       </span>
                                       {label}
                                     </span>
                                   );
                                 })}
                               </div>
                             )}
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteTask(task);
                            }}
                            className="text-muted-foreground hover:text-destructive size-8"
                          >
                             <Trash className="size-4" />
                          </Button>
                       </div>
                    </div>
                 )
              })}
            </div>

        </div>
      </main>
    </>
  );

  return (
    <>
      <div className="relative flex h-full min-h-0 flex-col bg-transparent">{content}</div>
      <TaskDetailModal
        taskId={selectedTaskId}
        onClose={() => setSelectedTaskId(null)}
        onSaved={() => {
          void refetch();
          queryClient.invalidateQueries({ queryKey: ["tasks-unseen-count"] });
        }}
        onViewed={() => {
          void refetch();
          queryClient.invalidateQueries({ queryKey: ["tasks-unseen-count"] });
        }}
      />

      <CreateTaskModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false);
          void refetch();
        }}
      />
    </>
  );
}

function formatDate(d: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(d);
}

function formatDateOnly(value: string): string {
  const parsed = parseBackendDateOnly(value);
  if (!parsed) return value;
  return formatDate(parsed);
}

function isDueDateOverdue(value: string): boolean {
  const parsed = parseBackendDateOnly(value);
  if (!parsed) return false;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return parsed.getTime() < today.getTime();
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const map: Record<TaskStatus, { label: string; cls: string }> = {
    todo: { label: "To do", cls: "border-stone-200 text-stone-700 bg-stone-50 dark:border-stone-800 dark:text-stone-300 dark:bg-stone-950/30" },
    in_progress: { label: "In progress", cls: "border-amber-200 text-amber-700 bg-amber-50 dark:border-amber-800 dark:text-amber-300 dark:bg-amber-950/30" },
    done: { label: "Done", cls: "border-emerald-200 text-emerald-700 bg-emerald-50 dark:border-emerald-800 dark:text-emerald-300 dark:bg-emerald-950/30" },
  };
  const { label, cls } = map[status];
  return <Badge variant="outline" className={cn("font-normal", cls)}>{label}</Badge>;
}

function PriorityBadge({ priority }: { priority: TaskPriority }) {
  const map: Record<TaskPriority, { label: string; cls: string; icon?: React.ElementType }> = {
    low: { label: "Low", cls: "border-slate-200 text-slate-600 bg-slate-50 dark:border-slate-800 dark:text-slate-400 dark:bg-slate-950/30" },
    medium: { label: "Medium", cls: "border-orange-200 text-orange-600 bg-orange-50 dark:border-orange-800 dark:text-orange-400 dark:bg-orange-950/30" },
    high: { label: "High", cls: "border-amber-200 text-amber-600 bg-amber-50 dark:border-amber-800 dark:text-amber-400 dark:bg-amber-950/30", icon: WarningCircle },
    urgent: { label: "Urgent", cls: "border-rose-200 text-rose-600 bg-rose-50 dark:border-rose-800 dark:text-rose-400 dark:bg-rose-950/30", icon: WarningCircle },
  };

  const { label, cls, icon: Icon } = map[priority] ?? { label: priority, cls: "bg-muted" };

  return (
    <Badge variant="outline" className={cn("gap-1 font-normal", cls)}>
      {Icon && <Icon className="size-3" />}
      {label}
    </Badge>
  );
}

// Sortable table header component
function SortableHeader({
  field,
  label,
  sort,
  onSort,
  className,
}: {
  field: SortField;
  label: string;
  sort: { field: SortField; dir: SortDir };
  onSort: (field: SortField) => void;
  className?: string;
}) {
  const isActive = sort.field === field;
  return (
    <TableHead className={cn("type-overline", className)}>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => onSort(field)}
        className={cn(
          "flex items-center gap-1 hover:text-foreground transition-colors select-none h-auto px-0 py-0",
          isActive && "text-foreground"
        )}
      >
        {label}
        {isActive ? (
          sort.dir === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />
        ) : (
          <ArrowsDownUp className="size-3 opacity-50" />
        )}
      </Button>
    </TableHead>
  );
}

// Combined filters popover for Status, Priority, and Category
function FiltersPopover({
  filter,
  setFilter,
  uniqueCategories,
}: {
  filter: Filter;
  setFilter: React.Dispatch<React.SetStateAction<Filter>>;
  uniqueCategories: string[];
}) {
  const [open, setOpen] = React.useState(false);

  const activeCount = [
    filter.taskStatus !== "all",
    filter.priority !== "all",
    filter.category !== "",
    filter.scope !== "all",
    filter.dueFrom !== "" || filter.dueTo !== "",
  ].filter(Boolean).length;

  const clear = () => {
    setFilter((f) => ({ ...f, taskStatus: "all", priority: "all", category: "", scope: "all", dueFrom: "", dueTo: "" }));
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button
          type="button"
          variant="ghost"
          className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-xl bg-muted/20 border border-border/5 hover:bg-muted/30 transition-colors h-auto type-control",
            activeCount > 0 && "bg-primary/10 border-primary/20 text-primary"
          )}
        >
          <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
          </svg>
          <span className="whitespace-nowrap">Filters</span>
          {activeCount > 0 && (
            <>
              <span className="size-5 flex items-center justify-center rounded-full bg-primary text-primary-foreground type-control-compact">
                {activeCount}
              </span>
              <span
                role="button"
                onClick={(e) => { e.stopPropagation(); clear(); }}
                className="p-0.5 rounded-full hover:bg-primary/20 transition-colors"
              >
                <X className="size-3" />
              </span>
            </>
          )}
        </Button>
      </Popover.Trigger>
      <Popover.Content
        align="start"
        sideOffset={6}
        className="z-[70] rounded-xl border bg-background shadow-xl w-[280px] p-3 space-y-3"
      >
        <div className="space-y-3">
          <div>
            <label className="type-overline mb-1.5 block">Scope</label>
            <Select
              value={filter.scope}
              onValueChange={(v) => setFilter((f) => ({ ...f, scope: v as TaskScope }))}
            >
              <SelectTrigger className="w-full rounded-lg">
                <SelectValue placeholder="Scope" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All tasks</SelectItem>
                <SelectItem value="created">Created by me</SelectItem>
                <SelectItem value="assigned">Assigned to me</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="type-overline mb-1.5 block">Status</label>
            <Select
              value={filter.taskStatus}
              onValueChange={(v) => setFilter((f) => ({ ...f, taskStatus: v as Filter["taskStatus"] }))}
            >
              <SelectTrigger className="w-full rounded-lg">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="todo">To do</SelectItem>
                <SelectItem value="in_progress">In progress</SelectItem>
                <SelectItem value="done">Done</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="type-overline mb-1.5 block">Priority</label>
            <Select
              value={filter.priority}
              onValueChange={(v) => setFilter((f) => ({ ...f, priority: v as Filter["priority"] }))}
            >
              <SelectTrigger className="w-full rounded-lg">
                <SelectValue placeholder="Priority" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All priorities</SelectItem>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="urgent">Urgent</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="type-overline mb-1.5 block">Due date</label>
            <DateRangePicker
              value={{ startDate: filter.dueFrom, endDate: filter.dueTo }}
              onChange={(range) => setFilter((f) => ({ ...f, dueFrom: range.startDate, dueTo: range.endDate }))}
              presets={TASK_DUE_DATE_PRESETS}
              showReset={false}
              clearable
              allowOpenEnded
              disableFuture={false}
              placeholder="Any date"
            />
          </div>

          {uniqueCategories.length > 0 && (
            <div>
              <label className="type-overline mb-1.5 block">Category</label>
              <Select
                value={filter.category || "all"}
                onValueChange={(v) => setFilter((f) => ({ ...f, category: v === "all" ? "" : v }))}
              >
                <SelectTrigger className="w-full rounded-lg">
                  <SelectValue placeholder="Category" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All categories</SelectItem>
                  {uniqueCategories.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <div className="flex justify-between pt-2 border-t">
          <Button type="button" variant="ghost" size="sm" onClick={clear} disabled={activeCount === 0}>
            Clear all
          </Button>
          <Button type="button" variant="default" size="sm" onClick={() => setOpen(false)}>
            Done
          </Button>
        </div>
      </Popover.Content>
    </Popover.Root>
  );
}
