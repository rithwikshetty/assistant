
import { useEffect, useState, useCallback } from "react";
import { listTasks, type Task } from "@/lib/api/tasks";
import { Clock, ArrowRight, Sparkle, Circle } from "@phosphor-icons/react";
import { parseBackendDateOnly } from "@/lib/datetime";
import { Link } from "react-router-dom";
import { useAuth } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CollapsibleInlineList } from "@/components/ui/collapsible-inline-list";

type UpcomingTasksProps = {
  variant?: "list" | "inline";
  /** When true, renders without its own border/bg (parent card provides chrome) */
  bare?: boolean;
};

export const UpcomingTasks: React.FC<UpcomingTasksProps> = ({ variant = "list", bare = false }) => {
  const { isBackendAuthenticated } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Don't fetch until backend auth is confirmed
    if (!isBackendAuthenticated) {
      return;
    }

    async function fetchUpcomingTasks() {
      try {
        setIsLoading(true);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const weekFromNow = new Date();
        weekFromNow.setDate(weekFromNow.getDate() + 7);
        const toYmd = (value: Date) => {
          const yyyy = value.getFullYear();
          const mm = String(value.getMonth() + 1).padStart(2, "0");
          const dd = String(value.getDate()).padStart(2, "0");
          return `${yyyy}-${mm}-${dd}`;
        };

        // Include overdue tasks by not setting due_from
        const upcomingTasks = await listTasks({
          view: "active",
          scope: "all",
          due_to: toYmd(weekFromNow),
        });

        const todayStartMs = today.getTime();

        // Sort: overdue first, then by due date (earliest first), then by priority
        const sorted = upcomingTasks.sort((a, b) => {
          const aParsed = a.due_at ? parseBackendDateOnly(a.due_at) : null;
          const bParsed = b.due_at ? parseBackendDateOnly(b.due_at) : null;
          const aTime = aParsed ? aParsed.getTime() : Infinity;
          const bTime = bParsed ? bParsed.getTime() : Infinity;

          const aOverdue = aTime < todayStartMs && aTime !== Infinity;
          const bOverdue = bTime < todayStartMs && bTime !== Infinity;

          // Overdue tasks come first
          if (aOverdue && !bOverdue) return -1;
          if (!aOverdue && bOverdue) return 1;

          // Both overdue or both not overdue: sort by due date
          if (aTime !== Infinity && bTime !== Infinity) {
            return aTime - bTime;
          }
          if (aTime !== Infinity) return -1;
          if (bTime !== Infinity) return 1;

          // No due dates: sort by priority
          const priorityOrder = { urgent: 0, high: 1, medium: 2, low: 3 };
          return priorityOrder[a.priority] - priorityOrder[b.priority];
        });

        setTasks(sorted);
      } catch (err) {
        console.error("Failed to fetch upcoming tasks:", err);
      } finally {
        setIsLoading(false);
      }
    }

    fetchUpcomingTasks();
  }, [isBackendAuthenticated]);

  // Helper to set prompt text and focus composer
  const setPromptAndFocus = useCallback((prompt: string) => {
    const el = document.querySelector<HTMLTextAreaElement>('textarea[name="input"]');
    if (el) {
      // Use native setter to trigger React state update
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        'value'
      )?.set;
      nativeInputValueSetter?.call(el, prompt);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.focus({ preventScroll: true });
      const len = el.value.length;
      el.setSelectionRange(len, len);
    }
  }, []);

  const truncate = (text: string, max = 70) => {
    if (text.length <= max) return text;
    const cut = text.slice(0, max);
    const lastSpace = cut.lastIndexOf(" ");
    return (lastSpace > 40 ? cut.slice(0, lastSpace) : cut).trimEnd() + "\u2026";
  };

  const generatePrompt = (task: Task) => {
    return `Identify the task: "${task.title}" from my task list, read its description and comments if any, and let's work on this together`;
  };

  const formatDueDate = (dueAt: string | null | undefined) => {
    if (!dueAt) return null;

    const dueDate = parseBackendDateOnly(dueAt);
    if (!dueDate) return null;

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const due = new Date(dueDate.getFullYear(), dueDate.getMonth(), dueDate.getDate());

    const diffMs = due.getTime() - today.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays < 0) {
      const overdueDays = Math.abs(diffDays);
      if (overdueDays === 1) return "1 day overdue";
      return `${overdueDays} days overdue`;
    }
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Tomorrow";
    if (diffDays <= 7) return `In ${diffDays}d`;

    return dueDate.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  };

  const isOverdue = (dueAt: string | null | undefined) => {
    if (!dueAt) return false;
    const dueDate = parseBackendDateOnly(dueAt);
    if (!dueDate) return false;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const due = new Date(dueDate.getFullYear(), dueDate.getMonth(), dueDate.getDate());
    return due.getTime() < today.getTime();
  };

  if (variant === "inline") {
    return (
      <InlineTaskList
        tasks={tasks}
        isLoading={isLoading}
        truncate={truncate}
        generatePrompt={generatePrompt}
        setPromptAndFocus={setPromptAndFocus}
        formatDueDate={formatDueDate}
        isOverdue={isOverdue}
        bare={bare}
      />
    );
  }

  if (isLoading) {
    return (
      <div className="w-full max-w-[var(--thread-max-width)] mx-auto">
        <div className="rounded-xl border border-border/50 overflow-hidden bg-muted/20">
          <div className="px-3 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="size-4 text-muted-foreground" />
              <span className="type-size-12 font-medium text-muted-foreground">Loading tasks</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="w-full max-w-[var(--thread-max-width)] mx-auto">
        <div className="rounded-xl border border-border/50 bg-muted/20 overflow-hidden">
          <div className="px-3 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Clock className="size-4" />
              <span className="type-size-12 font-medium">No upcoming tasks</span>
            </div>
            <Link
              to="/tasks"
              className="type-size-10 text-muted-foreground/70 hover:text-foreground flex items-center gap-1 transition-colors"
            >
              View all
              <ArrowRight className="size-3" />
            </Link>
          </div>
          <div className="px-3 pb-2.5">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setPromptAndFocus("Create a new task for me")}
              className="w-full h-auto justify-start text-left group px-2.5 py-2 rounded-lg bg-background/40 hover:bg-muted/50 border border-border/30"
            >
              <Sparkle className="size-3.5 text-primary/60 group-hover:text-primary transition-colors" />
              <span className="type-size-10 text-muted-foreground group-hover:text-foreground transition-colors">
                Ask me to create a task for you
              </span>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const overdueCount = tasks.filter(t => isOverdue(t.due_at)).length;

  return (
    <div className="w-full max-w-[var(--thread-max-width)] mx-auto">
      <div className="rounded-xl overflow-hidden bg-muted/20">
        {/* Header */}
        <div className="px-3 py-2.5 flex items-center justify-between gap-2 border-b border-border/40">
          <div className="flex items-center gap-2">
            <Clock className="size-4 text-muted-foreground" />
            <div className="flex items-center gap-2">
              <span className="type-size-12 font-semibold text-foreground">
                Upcoming Tasks
              </span>
              <div className="flex items-center gap-1.5 type-size-10">
                <span className="px-1.5 py-0.5 rounded-full bg-background/60 text-foreground/70 font-medium">
                  {tasks.length} pending
                </span>
                {overdueCount > 0 && (
                  <span className="px-1.5 py-0.5 rounded-full bg-red-500/10 text-red-600 dark:text-red-400 font-semibold">
                    {overdueCount} overdue
                  </span>
                )}
              </div>
            </div>
          </div>
          <Link
            to="/tasks"
            className="type-size-10 text-muted-foreground/70 hover:text-foreground flex items-center gap-1 transition-colors shrink-0"
          >
            View all
            <ArrowRight className="size-3" />
          </Link>
        </div>

        {/* Task list - always visible and scrollable */}
        <div className="divide-y divide-border/40 max-h-[280px] overflow-y-auto bg-background/30">
          {tasks.map((task) => {
            const taskIsOverdue = isOverdue(task.due_at);
            const priorityColor =
              task.priority === 'urgent' ? 'text-red-600 dark:text-red-400' :
                task.priority === 'high' ? 'text-orange-600 dark:text-orange-400' :
                  task.priority === 'medium' ? 'text-orange-600 dark:text-orange-400' :
                    'text-gray-600 dark:text-gray-400';
            const categoryLabel = task.category?.trim() || null;
            const dueLabel = formatDueDate(task.due_at);

            return (
              <Button
                key={task.id}
                type="button"
                variant="ghost"
                onClick={() => setPromptAndFocus(generatePrompt(task))}
                className="w-full h-auto justify-start text-left group/item px-3 py-2.5 hover:bg-muted/50 rounded-none"
              >
                <div className="flex items-start justify-between gap-3 w-full">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`type-size-12 font-medium truncate ${taskIsOverdue ? 'text-red-600 dark:text-red-400' : 'text-foreground/90'}`}>
                        {truncate(task.title)}
                      </span>
                      {categoryLabel && (
                        <span className="type-size-10 px-1.5 py-0.5 rounded-full bg-muted/50 text-muted-foreground truncate max-w-[100px]">
                          {categoryLabel}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-0.5 shrink-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`type-size-10 font-medium uppercase tracking-wider ${priorityColor}`}>
                        {task.priority}
                      </span>
                      {dueLabel && (
                        <span className={`type-size-10 ${taskIsOverdue ? 'text-red-600 dark:text-red-400 font-medium' : 'text-muted-foreground/70'}`}>
                          {dueLabel}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </Button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const InlineTaskList: React.FC<{
  tasks: Task[];
  isLoading: boolean;
  truncate: (text: string, max?: number) => string;
  generatePrompt: (task: Task) => string;
  setPromptAndFocus: (prompt: string) => void;
  formatDueDate: (dueAt: string | null | undefined) => string | null;
  isOverdue: (dueAt: string | null | undefined) => boolean;
  bare?: boolean;
}> = ({ tasks, isLoading, truncate, generatePrompt, setPromptAndFocus, formatDueDate, isOverdue, bare = false }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const overdueCount = tasks.filter((task) => isOverdue(task.due_at)).length;

  if (isLoading) {
    return (
      <div className={cn("w-full", !bare && "mb-2")}>
        <div className={cn(
          "flex w-full items-center gap-2 px-3.5 py-2 type-size-12 font-medium text-foreground/70",
          !bare && "rounded-lg border border-border/60 bg-background/50 backdrop-blur-sm"
        )}>
          <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
          <span>Loading tasks</span>
        </div>
      </div>
    );
  }

  if (tasks.length === 0) return null;

  return (
    <CollapsibleInlineList
      icon={<Clock className="h-3.5 w-3.5 text-primary" />}
      label="Upcoming tasks"
      overlayExpand={!bare}
      bare={bare}
      headerExtra={
        <>
          <span className="rounded-full bg-muted/40 px-1.5 py-0.5 type-size-10 text-muted-foreground/70 leading-none">
            {tasks.length}
          </span>
          {overdueCount > 0 && (
            <span className="rounded-full bg-red-500/10 px-1.5 py-0.5 type-size-10 text-red-500/90 dark:text-red-400/90 leading-none">
              {overdueCount} overdue
            </span>
          )}
        </>
      }
      headerActions={
        <Link
          to="/tasks"
          onClick={(e) => e.stopPropagation()}
          className="type-size-10 text-muted-foreground/50 hover:text-foreground transition-colors flex items-center gap-0.5"
        >
          View all <ArrowRight className="inline size-2.5" />
        </Link>
      }
      expanded={isExpanded}
      onToggle={() => setIsExpanded(!isExpanded)}
      scrollable
      className={bare ? undefined : "mb-2"}
    >
      {tasks.map((task) => {
        const taskIsOverdue = isOverdue(task.due_at);
        const dueLabel = formatDueDate(task.due_at);
        return (
          <Button
            key={task.id}
            type="button"
            variant="ghost"
            onClick={() => setPromptAndFocus(generatePrompt(task))}
            className="group flex min-h-[2rem] w-full items-center justify-between gap-2 px-3.5 py-1.5 text-left transition-colors hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 h-auto rounded-none active:!scale-100"
          >
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
              <Circle
                className={cn(
                  "size-3.5 shrink-0 transition-colors",
                  taskIsOverdue
                    ? "text-red-500 dark:text-red-400"
                    : "text-muted-foreground/40 group-hover:text-foreground/60"
                )}
              />
              <span
                className={cn(
                  "type-size-12 leading-relaxed truncate font-medium",
                  taskIsOverdue
                    ? "text-red-600 dark:text-red-400"
                    : "text-foreground/85 group-hover:text-foreground"
                )}
              >
                {truncate(task.title, 60)}
              </span>
            </div>
            {dueLabel && (
              <span
                className={cn(
                  "type-size-10 shrink-0 text-right",
                  taskIsOverdue
                    ? "text-red-500/80 dark:text-red-400/80 font-medium"
                    : "text-muted-foreground/50"
                )}
              >
                {dueLabel}
              </span>
            )}
          </Button>
        );
      })}
    </CollapsibleInlineList>
  );
};
