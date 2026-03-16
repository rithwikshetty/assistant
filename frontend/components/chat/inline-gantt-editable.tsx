
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { CaretDoubleLeft, Copy, Check, SpinnerGap } from "@phosphor-icons/react";

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type ViewMode = "Day" | "Week" | "Month" | "Year";

export type GanttTask = {
  id: string;
  name: string;
  start: string;
  end: string;
  progress?: number;
  dependencies?: string;
  custom_bar_color?: string;
};

export type GanttSpec = {
  title: string;
  tasks: GanttTask[];
  view_mode?: ViewMode;
  readonly?: boolean;
};

export type GanttHandle = {
  measure: () => { width: number; height: number } | null;
  copyImage: () => Promise<void>;
  setViewMode: (mode: ViewMode) => void;
  scrollToStart: () => void;
  flush: () => Promise<void>;
};

type ReadonlyGanttProps = {
  spec: GanttSpec;
};

type ParsedTask = GanttTask & {
  startDate: Date;
  endDate: Date;
  durationDays: number;
};

type TimelineBar = {
  task: ParsedTask;
  left: number;
  width: number;
  color: string;
  textColor: string;
  progressWidth: number;
  roundedProgress?: number;
  progressSuffix?: string;
  rangeLabel: string;
  fullLabel: string;
  compactLabel: string;
};

type TimelineSegment = {
  key: string;
  label: string;
  left: number;
  width: number;
  showLabel: boolean;
};

const DAY_MS = 24 * 60 * 60 * 1000;
const MIN_BAR_WIDTH = 12;
const NAME_COLUMN_WIDTH = 240;
const ROW_HEIGHT = 52;
const BASE_CANVAS_WIDTH = 640;
const VIEW_MODES: readonly ViewMode[] = ["Day", "Week", "Month", "Year"];

const VIEW_MODE_CONFIG: Record<ViewMode, { pxPerDay: number }> = {
  Day: { pxPerDay: 48 },
  Week: { pxPerDay: 20 },
  Month: { pxPerDay: 12 },
  Year: { pxPerDay: 4 },
};

const monthFormatter = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });
const yearFormatter = new Intl.DateTimeFormat(undefined, { year: "numeric" });
const rangeFormatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });

type TimelineData = {
  width: number;
  bars: TimelineBar[];
  todayX?: number;
  majorSegments: TimelineSegment[];
  minorSegments: TimelineSegment[];
  gridLines: number[];
};

export const InlineGanttEditable = forwardRef<GanttHandle, ReadonlyGanttProps>(function InlineGantt({ spec }, ref) {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(() => spec.view_mode ?? "Month");
  const [isCopying, setIsCopying] = useState(false);
  const [copySucceeded, setCopySucceeded] = useState(false);
  const copyResetRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const specViewModeRef = useRef<ViewMode | undefined>(spec.view_mode);

  const parsedTasks = useMemo(() => spec.tasks.map(normaliseTask), [spec.tasks]);

  const timeline = useMemo(() => buildTimeline(parsedTasks, viewMode), [parsedTasks, viewMode]);

  useEffect(() => {
    if (spec.view_mode && spec.view_mode !== specViewModeRef.current) {
      specViewModeRef.current = spec.view_mode;
      setViewMode(spec.view_mode);
    } else if (!spec.view_mode && specViewModeRef.current !== undefined) {
      specViewModeRef.current = undefined;
    }
  }, [spec.view_mode]);

  const scrollToStart = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollTo({ left: 0, behavior: "smooth" });
  }, []);

  const handleCopyImage = useCallback(async () => {
    if (!canvasRef.current || isCopying) return;
    if (
      typeof navigator === "undefined" ||
      !navigator.clipboard ||
      typeof navigator.clipboard.write !== "function" ||
      typeof ClipboardItem === "undefined"
    ) {
      console.warn("Clipboard image copy is not supported in this browser context.");
      return;
    }
    setIsCopying(true);
    const computed = getComputedStyle(document.documentElement);
    const background = computed.getPropertyValue("--background")?.trim() || computed.getPropertyValue("--color-background")?.trim() || "#ffffff";
    try {
      const { toBlob } = await import("html-to-image");
      const blob = await toBlob(canvasRef.current, {
        backgroundColor: background,
        pixelRatio: 2,
        cacheBust: true,
      });
      if (!blob) {
        console.warn("Failed to generate image for clipboard copy.");
        return;
      }
      const clipboardItem = new ClipboardItem({ [blob.type]: blob });
      await navigator.clipboard.write([clipboardItem]);
      setCopySucceeded(true);
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
      copyResetRef.current = setTimeout(() => setCopySucceeded(false), 2000);
    } catch (error) {
      console.warn("Unable to copy Gantt snapshot to clipboard:", error);
    } finally {
      setIsCopying(false);
    }
  }, [isCopying]);

  useEffect(() => {
    return () => {
      if (copyResetRef.current) {
        clearTimeout(copyResetRef.current);
      }
    };
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      measure: () => {
        const el = canvasRef.current;
        if (!el) return null;
        return { width: el.scrollWidth, height: el.scrollHeight };
      },
      copyImage: handleCopyImage,
      setViewMode: (mode: ViewMode) => setViewMode(mode),
      scrollToStart,
      flush: async () => {
        /* no-op for read-only */
      },
    }),
    [handleCopyImage, scrollToStart]
  );

  return (
    <div className="relative overflow-hidden inline-gantt-chart">
      <div ref={scrollContainerRef} className="overflow-x-auto">
          {timeline ? (
            <div
              ref={canvasRef}
              className="inline-grid"
              style={{ gridTemplateColumns: `${NAME_COLUMN_WIDTH}px ${timeline.width}px` }}
            >
              <div className="border-b border-border/20 px-4 py-2.5 type-size-12 font-medium uppercase tracking-wide text-muted-foreground">
                Task
              </div>
              <TimelineHeader
                width={timeline.width}
                majorSegments={timeline.majorSegments}
                minorSegments={timeline.minorSegments}
                todayX={timeline.todayX}
              />

              {timeline.bars.length === 0 ? (
                <>
                  <div className="col-span-2 flex h-32 items-center justify-center type-size-14 text-muted-foreground">
                    No tasks to display.
                  </div>
                </>
              ) : (
                timeline.bars.map((bar, index) => {
                  const useCompactBarLabel = bar.width < 132;
                  const barLabel =
                    useCompactBarLabel && typeof bar.roundedProgress === "number"
                      ? `${bar.roundedProgress}%`
                      : useCompactBarLabel
                        ? bar.compactLabel
                        : bar.fullLabel;
                  return (
                    <React.Fragment key={bar.task.id}>
                      <div
                        className={cn(
                          "flex flex-col justify-center gap-1 border-b border-border/20 px-4",
                          index % 2 === 1 && "bg-muted/10 dark:bg-muted/5"
                        )}
                        style={{ height: ROW_HEIGHT }}
                      >
                        <div className="flex items-baseline gap-1 type-size-14 font-medium leading-tight text-foreground">
                          <span className="min-w-0 truncate">{bar.task.name}</span>
                          {bar.progressSuffix ? (
                            <span className="flex-shrink-0 type-size-12 font-medium text-muted-foreground">{bar.progressSuffix}</span>
                          ) : null}
                        </div>
                        <div className="type-size-12 text-muted-foreground">{bar.rangeLabel}</div>
                      </div>
                      <div
                        className={cn(
                          "relative border-b border-border/20",
                          index % 2 === 1 && "bg-muted/5 dark:bg-muted/[0.03]"
                        )}
                        style={{ height: ROW_HEIGHT }}
                      >
                        <RowBackground gridLines={timeline.gridLines} height={ROW_HEIGHT} todayX={timeline.todayX} />
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div
                              className="absolute top-[14px] h-6 w-fit min-w-[40px] overflow-hidden rounded-full shadow-sm ring-1 ring-black/5 dark:ring-white/10"
                              style={{
                                left: `${bar.left}px`,
                                width: `${bar.width}px`,
                                backgroundColor: bar.color,
                                color: bar.textColor,
                              }}
                            >
                              {bar.progressWidth > 0 && (
                                <span
                                  className="absolute inset-y-0 left-0 z-0 rounded-full transition-all duration-300 ease-out"
                                  style={{
                                    width: `${bar.progressWidth}px`,
                                    backgroundColor:
                                      bar.textColor === "#ffffff"
                                        ? "rgba(255,255,255,0.35)"
                                        : "rgba(17,24,39,0.18)",
                                  }}
                                  aria-hidden="true"
                                />
                              )}
                              <span className="relative z-[1] flex h-full w-full items-center overflow-hidden px-3 type-size-12 font-medium">
                                <span className="min-w-0 truncate">{barLabel}</span>
                              </span>
                            </div>
                          </TooltipTrigger>
                          <TooltipContent side="top" align="start" sideOffset={8} className="max-w-xs">
                            <div className="space-y-1">
                              <div className="type-size-12 font-semibold leading-snug text-primary-foreground">{bar.task.name}</div>
                              {typeof bar.roundedProgress === "number" ? (
                                <div className="type-size-10 uppercase tracking-wide text-primary-foreground/80">
                                  Progress {bar.roundedProgress}%
                                </div>
                              ) : null}
                              <div className="type-size-10 text-primary-foreground/80">{bar.rangeLabel}</div>
                            </div>
                          </TooltipContent>
                        </Tooltip>
                      </div>
                    </React.Fragment>
                  );
                })
              )}
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center type-size-14 text-muted-foreground">
              Unable to render chart.
            </div>
          )}
        </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/20 px-4 py-2 type-size-12">
        <div className="flex flex-wrap items-center gap-0.5">
          {VIEW_MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setViewMode(mode)}
              className={cn(
                "rounded-full px-2.5 py-1 type-size-12 font-medium transition-colors",
                mode === viewMode
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {mode}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={scrollToStart}
            className="flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
            title="Scroll to project start"
          >
            <CaretDoubleLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={handleCopyImage}
            className="flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
            title={copySucceeded ? "Copied!" : "Copy timeline to clipboard"}
            disabled={isCopying}
          >
            {isCopying ? <SpinnerGap className="h-3.5 w-3.5 animate-spin" /> : copySucceeded ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
    </div>
  );
});

InlineGanttEditable.displayName = "InlineGanttEditable";

function TimelineHeader({
  width,
  majorSegments,
  minorSegments,
  todayX,
}: {
  width: number;
  majorSegments: TimelineSegment[];
  minorSegments: TimelineSegment[];
  todayX?: number;
}) {
  const hasMajor = majorSegments.length > 0;
  return (
    <div className="border-b border-border/20 px-0">
      <div className="relative" style={{ width }}>
        {hasMajor && (
          <div className="relative h-8 border-b border-border/15">
            {majorSegments.map((segment) => (
              <div
                key={segment.key}
                className="absolute flex h-full items-center justify-center px-2 type-size-12 font-semibold uppercase tracking-wide text-muted-foreground"
                style={{ left: `${segment.left}px`, width: `${segment.width}px` }}
              >
                {segment.showLabel ? segment.label : null}
              </div>
            ))}
          </div>
        )}
        <div className={cn("relative", hasMajor ? "h-8" : "h-9")}>
          <div className="absolute inset-0 border-b border-border/15" />
          {minorSegments.map((segment, index) => (
            <div
              key={segment.key}
              className={cn(
                "pointer-events-none absolute top-0 flex h-full items-center justify-center px-1 type-size-12 font-medium text-muted-foreground",
                index % 2 === 0 ? "" : "bg-muted/10 dark:bg-muted/5"
              )}
              style={{ left: `${segment.left}px`, width: `${segment.width}px` }}
            >
              {segment.showLabel ? segment.label : null}
            </div>
          ))}
          {typeof todayX === "number" && (
            <span
              className="absolute top-0 bottom-0 w-px bg-primary/70"
              style={{ left: `${todayX}px` }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function RowBackground({
  gridLines,
  height,
  todayX,
}: {
  gridLines: number[];
  height: number;
  todayX?: number;
}) {
  return (
    <div className="pointer-events-none absolute inset-0">
      {gridLines.map((x, index) =>
        index === 0 ? null : (
          <span
            key={`grid-${x}-${index}`}
            className="absolute top-0 h-full border-l border-border/20"
            style={{ left: `${x}px`, height }}
          />
        )
      )}
      {typeof todayX === "number" && (
        <span
          className="absolute top-0 bottom-0 w-px bg-primary/50"
          style={{ left: `${todayX}px` }}
        />
      )}
    </div>
  );
}

function buildTimeline(tasks: ParsedTask[], viewMode: ViewMode): TimelineData {
  if (tasks.length === 0) {
    return {
      width: BASE_CANVAS_WIDTH,
      bars: [],
      todayX: undefined,
      majorSegments: [],
      minorSegments: [],
      gridLines: [0, BASE_CANVAS_WIDTH],
    };
  }
  return computeTimeline(tasks, viewMode);
}

function computeTimeline(tasks: ParsedTask[], viewMode: ViewMode): TimelineData {
  const earliest = tasks.reduce((acc, task) => (task.startDate < acc ? task.startDate : acc), tasks[0].startDate);
  const latest = tasks.reduce((acc, task) => (task.endDate > acc ? task.endDate : acc), tasks[0].endDate);

  const durationMs = Math.max(DAY_MS, latest.getTime() - earliest.getTime() + DAY_MS);
  const totalDays = Math.max(1, Math.round(durationMs / DAY_MS));
  const pxPerDay = VIEW_MODE_CONFIG[viewMode].pxPerDay;
  const width = Math.max(BASE_CANVAS_WIDTH, Math.round(totalDays * pxPerDay));
  const scale = width / durationMs;

  const { majorSegments, minorSegments, gridLines } = generateSegments(earliest, latest, viewMode, scale, width);

  const bars: TimelineBar[] = tasks.map((task) => {
    const startOffset = task.startDate.getTime() - earliest.getTime();
    const endOffset = task.endDate.getTime() - earliest.getTime() + DAY_MS;
    const left = Math.max(0, startOffset * scale);
    const widthPx = Math.max(MIN_BAR_WIDTH, endOffset * scale - startOffset * scale);
    const color = task.custom_bar_color?.trim().length ? task.custom_bar_color.trim() : defaultBarColour;
    const textColor = computeTextColor(color);
    const progress = typeof task.progress === "number" ? clamp(task.progress, 0, 100) : undefined;
    const progressWidth = progress !== undefined ? (widthPx * progress) / 100 : 0;
    const roundedProgress = progress !== undefined ? Math.round(progress) : undefined;
    return {
      task,
      left,
      width: widthPx,
      color,
      textColor,
      progressWidth,
      roundedProgress,
      progressSuffix: typeof roundedProgress === "number" ? `(${roundedProgress}%)` : undefined,
      rangeLabel: formatRange(task.startDate, task.endDate),
      fullLabel: formatTaskDisplayName(task.name, progress),
      compactLabel: compactTaskName(task.name),
    };
  });

  const today = startOfDayUtc(new Date());
  const todayOffset = today.getTime() - earliest.getTime();
  const todayX = todayOffset >= 0 && todayOffset <= durationMs ? todayOffset * scale : undefined;

  return {
    width,
    bars,
    todayX,
    majorSegments,
    minorSegments,
    gridLines,
  };
}

type TimeUnit = "day" | "week" | "month" | "year" | "decade";

function generateSegments(start: Date, end: Date, viewMode: ViewMode, scale: number, width: number) {
  const minorUnit = getMinorUnit(viewMode);
  const majorUnit = getMajorUnit(viewMode);

  const minorSegments = createSegments(start, end, minorUnit, scale, viewMode, "minor");
  const majorSegments = createSegments(start, end, majorUnit, scale, viewMode, "major");

  const gridSet = new Set<number>([0, width]);
  for (const segment of minorSegments) {
    gridSet.add(Math.round(segment.left));
    gridSet.add(Math.round(segment.left + segment.width));
  }
  const gridLines = Array.from(gridSet).filter((value) => value >= 0 && value <= width).sort((a, b) => a - b);

  return { majorSegments, minorSegments, gridLines };
}

function createSegments(
  start: Date,
  end: Date,
  unit: TimeUnit | null,
  scale: number,
  viewMode: ViewMode,
  level: "major" | "minor",
): TimelineSegment[] {
  if (!unit) return [];
  const segments: TimelineSegment[] = [];
  const startMs = start.getTime();
  const endMs = end.getTime();
  const unitMs = getUnitDurationMs(unit);
  let cursor = alignToUnit(start, unit);
  let guard = 0;
  while (cursor.getTime() <= endMs + unitMs && guard < 4000) {
    const next = incrementUnit(cursor, unit);
    const segStart = Math.max(cursor.getTime(), startMs);
    const segEnd = Math.min(next.getTime(), endMs + DAY_MS);
    if (segEnd > segStart) {
      const left = Math.max(0, (segStart - startMs) * scale);
      const width = Math.max(1, (segEnd - segStart) * scale);
      const label = formatSegmentLabel(cursor, unit, viewMode, level);
      const minWidthForLabel = level === "major" ? 72 : viewMode === "Day" ? 28 : 44;
      segments.push({
        key: `${unit}-${cursor.toISOString()}-${level}`,
        label,
        left,
        width,
        showLabel: width >= minWidthForLabel,
      });
    }
    cursor = next;
    guard += 1;
  }
  return segments;
}

function getMinorUnit(viewMode: ViewMode): TimeUnit {
  switch (viewMode) {
    case "Day":
      return "day";
    case "Week":
      return "week";
    case "Month":
      return "month";
    case "Year":
      return "year";
    default:
      return "month";
  }
}

function getMajorUnit(viewMode: ViewMode): TimeUnit | null {
  switch (viewMode) {
    case "Day":
      return "month";
    case "Week":
      return "month";
    case "Month":
      return "year";
    case "Year":
      return "decade";
    default:
      return null;
  }
}

function getUnitDurationMs(unit: TimeUnit): number {
  switch (unit) {
    case "day":
      return DAY_MS;
    case "week":
      return DAY_MS * 7;
    case "month": {
      return DAY_MS * 31; // placeholder; actual handled via date diff
    }
    case "year":
      return DAY_MS * 366;
    case "decade":
      return DAY_MS * 366 * 10;
    default:
      return DAY_MS;
  }
}

function alignToUnit(date: Date, unit: TimeUnit): Date {
  const aligned = new Date(date);
  switch (unit) {
    case "week": {
      const day = aligned.getUTCDay();
      const diff = (day + 6) % 7;
      aligned.setUTCDate(aligned.getUTCDate() - diff);
      aligned.setUTCHours(0, 0, 0, 0);
      break;
    }
    case "month":
      aligned.setUTCDate(1);
      aligned.setUTCHours(0, 0, 0, 0);
      break;
    case "year":
      aligned.setUTCMonth(0, 1);
      aligned.setUTCHours(0, 0, 0, 0);
      break;
    case "decade": {
      const year = aligned.getUTCFullYear();
      const decadeStart = Math.floor(year / 10) * 10;
      aligned.setUTCFullYear(decadeStart, 0, 1);
      aligned.setUTCHours(0, 0, 0, 0);
      break;
    }
    default:
      aligned.setUTCHours(0, 0, 0, 0);
  }
  return aligned;
}

function incrementUnit(date: Date, unit: TimeUnit): Date {
  const next = new Date(date);
  switch (unit) {
    case "week":
      next.setUTCDate(next.getUTCDate() + 7);
      break;
    case "month":
      next.setUTCMonth(next.getUTCMonth() + 1);
      break;
    case "year":
      next.setUTCFullYear(next.getUTCFullYear() + 1);
      break;
    case "decade":
      next.setUTCFullYear(next.getUTCFullYear() + 10);
      break;
    default:
      next.setUTCDate(next.getUTCDate() + 1);
      break;
  }
  return next;
}

function formatSegmentLabel(date: Date, unit: TimeUnit, viewMode: ViewMode, level: "major" | "minor"): string {
  switch (unit) {
    case "day":
      return date.getUTCDate().toString();
    case "week":
      return `W${formatWeekNumber(date)}`;
    case "month":
      return level === "major" && viewMode === "Day" ? monthFormatter.format(date) : monthFormatter.format(date);
    case "year":
      return yearFormatter.format(date);
    case "decade": {
      const decade = Math.floor(date.getUTCFullYear() / 10) * 10;
      return `${decade}s`;
    }
    default:
      return "";
  }
}

function formatWeekNumber(date: Date): string {
  const target = new Date(date);
  target.setUTCDate(target.getUTCDate() + 4 - (target.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((target.getTime() - yearStart.getTime()) / DAY_MS + 1) / 7);
  return weekNo.toString().padStart(2, "0");
}

function normaliseTask(task: GanttTask): ParsedTask {
  const startDate = parseDateOnly(task.start);
  const endDate = parseDateOnly(task.end);
  const ordered = ensureChronologicalRange(startDate, endDate);
  const durationDays = Math.max(1, Math.round((ordered.end.getTime() - ordered.start.getTime()) / DAY_MS) + 1);
  return {
    ...task,
    startDate: ordered.start,
    endDate: ordered.end,
    durationDays,
  };
}

function ensureChronologicalRange(start: Date, end: Date): { start: Date; end: Date } {
  if (start.getTime() <= end.getTime()) return { start, end };
  return { start: end, end: start };
}

function parseDateOnly(value: string): Date {
  const parts = value.split("-").map(Number);
  if (parts.length >= 3) {
    const [year, month, day] = parts;
    return new Date(Date.UTC(year, (month ?? 1) - 1, day ?? 1));
  }
  const fallback = new Date(value);
  fallback.setUTCHours(0, 0, 0, 0);
  return fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function formatRange(start: Date, end: Date): string {
  if (start.getTime() === end.getTime()) {
    return rangeFormatter.format(start);
  }
  return `${rangeFormatter.format(start)} – ${rangeFormatter.format(end)}`;
}

function computeTextColor(hex: string): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return "#111827";
  const [r, g, b] = rgb.map((value) => value / 255);
  const luminance = 0.2126 * linearise(r) + 0.7152 * linearise(g) + 0.0722 * linearise(b);
  return luminance > 0.5 ? "#111827" : "#ffffff";
}

const defaultBarColour = "#64748b";

function compactTaskName(name: string): string {
  if (name.length <= 14) return name;
  return name.slice(0, 12).trimEnd();
}

function formatTaskDisplayName(name: string, progress?: number): string {
  if (typeof progress === "number" && Number.isFinite(progress)) {
    return `${name} (${Math.round(progress)}%)`;
  }
  return name;
}

function hexToRgb(hex: string): [number, number, number] | null {
  let value = hex.trim();
  if (!value.startsWith("#")) return null;
  value = value.slice(1);
  if (value.length === 3) {
    value = value.split("").map((char) => char + char).join("");
  }
  if (value.length !== 6) return null;
  const num = Number.parseInt(value, 16);
  if (Number.isNaN(num)) return null;
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function linearise(component: number): number {
  return component <= 0.03928 ? component / 12.92 : Math.pow((component + 0.055) / 1.055, 2.4);
}

function startOfDayUtc(date: Date): Date {
  const clone = new Date(date);
  clone.setUTCHours(0, 0, 0, 0);
  return clone;
}
