
import * as React from "react";
import * as Popover from "@radix-ui/react-popover";
import { CaretLeft, CaretRight, CalendarBlank as CalendarIcon, ArrowCounterClockwise, X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function fmtYmd(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseYmd(ymd: string | null | undefined): Date | null {
  if (!ymd) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]) - 1;
  const d = Number(m[3]);
  const dt = new Date(y, mo, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo || dt.getDate() !== d) return null;
  return dt;
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function endOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}
function addMonths(d: Date, n: number) {
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}
function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function isInRange(d: Date, start: Date | null, end: Date | null): boolean {
  if (!start || !end) return false;
  const time = d.getTime();
  return time >= start.getTime() && time <= end.getTime();
}

// Helper to get common date values
function getToday() {
  return new Date();
}
function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d;
}
function getWeekStart() {
  const now = new Date();
  const day = now.getDay();
  const start = new Date(now);
  start.setDate(now.getDate() - day);
  return start;
}
function getWeekEnd() {
  const start = getWeekStart();
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return end;
}
function getMonthStart() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
}
function getMonthEnd() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0);
}

export interface DateRange {
  startDate: string; // YYYY-MM-DD or "" for open-ended
  endDate: string;   // YYYY-MM-DD or "" for open-ended
}

export interface DateRangePreset {
  label: string;
  getRange: () => DateRange;
}

// Default presets for admin-style "last N days" usage
const DEFAULT_PRESETS: DateRangePreset[] = [
  {
    label: "7 days",
    getRange: () => {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - 6);
      return { startDate: fmtYmd(start), endDate: fmtYmd(end) };
    },
  },
  {
    label: "30 days",
    getRange: () => {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - 29);
      return { startDate: fmtYmd(start), endDate: fmtYmd(end) };
    },
  },
  {
    label: "90 days",
    getRange: () => {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - 89);
      return { startDate: fmtYmd(start), endDate: fmtYmd(end) };
    },
  },
];

// Task-focused presets for due date filtering
export const TASK_DUE_DATE_PRESETS: DateRangePreset[] = [
  {
    label: "Overdue",
    getRange: () => ({ startDate: "", endDate: fmtYmd(getYesterday()) }),
  },
  {
    label: "Today",
    getRange: () => {
      const today = fmtYmd(getToday());
      return { startDate: today, endDate: today };
    },
  },
  {
    label: "This week",
    getRange: () => ({ startDate: fmtYmd(getWeekStart()), endDate: fmtYmd(getWeekEnd()) }),
  },
  {
    label: "This month",
    getRange: () => ({ startDate: fmtYmd(getMonthStart()), endDate: fmtYmd(getMonthEnd()) }),
  },
];

export interface DateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
  /** Custom presets (defaults to 7/30/90 days) */
  presets?: DateRangePreset[];
  /** Show reset button inside popover (resets to first preset) */
  showReset?: boolean;
  /** Show X button on trigger to clear/reset selection */
  clearable?: boolean;
  /** Value to reset to when X is clicked (if not provided, clears to empty) */
  resetValue?: DateRange;
  /** Allow open-ended ranges (empty start or end) */
  allowOpenEnded?: boolean;
  /** Placeholder text when no date selected */
  placeholder?: string;
  /** Disable future dates */
  disableFuture?: boolean;
  disabled?: boolean;
  className?: string;
}

type SelectionState = "idle" | "selecting-start" | "selecting-end";

export function DateRangePicker({
  value,
  onChange,
  presets = DEFAULT_PRESETS,
  showReset = false,
  clearable = false,
  resetValue,
  allowOpenEnded: _allowOpenEnded = false,
  placeholder = "Select dates",
  disableFuture = true,
  disabled,
  className,
}: DateRangePickerProps) {
  const today = React.useMemo(() => new Date(), []);
  const startSelected = parseYmd(value.startDate);
  const endSelected = parseYmd(value.endDate);
  const hasValue = value.startDate || value.endDate;

  const [open, setOpen] = React.useState(false);
  const [monthCursor, setMonthCursor] = React.useState<Date>(startSelected || endSelected || startOfMonth(today));
  const [selectionState, setSelectionState] = React.useState<SelectionState>("idle");
  const [tempStart, setTempStart] = React.useState<Date | null>(null);
  const [hoveredDate, setHoveredDate] = React.useState<Date | null>(null);

  // Format display label
  const displayLabel = React.useMemo(() => {
    if (!startSelected && !endSelected) return placeholder;

    const formatShort = (d: Date) => `${MONTHS_SHORT[d.getMonth()]} ${d.getDate()}`;

    // Open-ended: only end date (e.g., "Before Jan 15")
    if (!startSelected && endSelected) {
      return `Before ${formatShort(endSelected)}`;
    }

    // Open-ended: only start date (e.g., "From Jan 15")
    if (startSelected && !endSelected) {
      return `From ${formatShort(startSelected)}`;
    }

    // Both dates selected
    if (startSelected && endSelected) {
      // Check if it matches a preset label for cleaner display
      for (const preset of presets) {
        const presetRange = preset.getRange();
        if (presetRange.startDate === value.startDate && presetRange.endDate === value.endDate) {
          // For "last N days" style presets, show that label
          if (preset.label.match(/^\d+ days$/)) {
            return `Last ${preset.label}`;
          }
          return preset.label;
        }
      }

      // Same day
      if (isSameDay(startSelected, endSelected)) {
        return formatShort(startSelected);
      }

      // Range display
      if (startSelected.getFullYear() === endSelected.getFullYear()) {
        return `${formatShort(startSelected)} – ${formatShort(endSelected)}`;
      }
      return `${formatShort(startSelected)}, ${startSelected.getFullYear()} – ${formatShort(endSelected)}, ${endSelected.getFullYear()}`;
    }

    return placeholder;
  }, [startSelected, endSelected, placeholder, presets, value.startDate, value.endDate]);

  // Apply a preset
  const applyPreset = (preset: DateRangePreset) => {
    const range = preset.getRange();
    onChange(range);
    setSelectionState("idle");
    setTempStart(null);
  };

  // Reset to first preset
  const reset = () => {
    if (presets.length > 0) {
      applyPreset(presets[0]);
    }
  };

  // Clear or reset selection
  const clear = () => {
    if (resetValue) {
      onChange(resetValue);
    } else {
      onChange({ startDate: "", endDate: "" });
    }
    setSelectionState("idle");
    setTempStart(null);
  };

  // Determine if X button should be shown
  const showClearButton = clearable && hasValue && (
    !resetValue ||
    value.startDate !== resetValue.startDate ||
    value.endDate !== resetValue.endDate
  );

  const handleDateClick = (d: Date) => {
    if (selectionState === "idle" || selectionState === "selecting-start") {
      setTempStart(d);
      setSelectionState("selecting-end");
    } else {
      // selecting-end
      if (tempStart) {
        const start = d < tempStart ? d : tempStart;
        const end = d < tempStart ? tempStart : d;
        onChange({ startDate: fmtYmd(start), endDate: fmtYmd(end) });
        setSelectionState("idle");
        setTempStart(null);
        setOpen(false);
      }
    }
  };

  const cal = buildCalendar(monthCursor);

  // Determine visual selection state
  const visualStart = selectionState === "selecting-end" ? tempStart : startSelected;
  const visualEnd = selectionState === "selecting-end" ? hoveredDate : endSelected;

  // Check if current selection matches a preset
  const isPresetSelected = (preset: DateRangePreset) => {
    const presetRange = preset.getRange();
    return presetRange.startDate === value.startDate && presetRange.endDate === value.endDate;
  };

  return (
    <Popover.Root open={open} onOpenChange={(n) => { if (disabled) return; setOpen(n); }}>
      <Popover.Trigger asChild>
        <Button
          variant="outline"
          disabled={disabled}
          className={cn(
            "h-8 px-2 sm:px-3 type-size-12 font-medium justify-start gap-1.5 sm:gap-2 min-w-0 sm:min-w-[140px] max-w-[180px] sm:max-w-none",
            !hasValue && "text-muted-foreground",
            className
          )}
        >
          <CalendarIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="truncate">{displayLabel}</span>
          {showClearButton && (
            <span
              role="button"
              onClick={(e) => { e.stopPropagation(); clear(); }}
              className="ml-auto p-0.5 rounded-full hover:bg-muted transition-colors shrink-0"
            >
              <X className="h-3 w-3" />
            </span>
          )}
        </Button>
      </Popover.Trigger>
      <Popover.Content
        align="end"
        sideOffset={6}
        className="z-[70] rounded-xl border bg-background shadow-xl w-[calc(100vw-1rem)] sm:w-[320px] max-w-[320px] p-3 sm:p-4"
      >
        {/* Quick select preset buttons */}
        {presets.length > 0 && (
          <div className="mb-4">
            <div className={cn(
              "grid gap-2",
              presets.length <= 3 ? "grid-cols-3" : "grid-cols-2"
            )}>
              {presets.map((preset) => (
                <Button
                  key={preset.label}
                  type="button"
                  variant={isPresetSelected(preset) ? "default" : "outline"}
                  size="sm"
                  onClick={() => applyPreset(preset)}
                >
                  {preset.label}
                </Button>
              ))}
            </div>
            {showReset && (
              <div className="flex justify-end mt-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={reset}
                  title={`Reset to ${presets[0]?.label || 'default'}`}
                >
                  <ArrowCounterClockwise className="h-3.5 w-3.5 mr-1.5" />
                  Reset
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Selection hint */}
        <div className="type-size-12 text-muted-foreground mb-3 text-center">
          {selectionState === "selecting-end"
            ? "Select end date"
            : "Select start date or use presets"}
        </div>

        {/* Calendar header */}
        <div className="flex items-center justify-between gap-2 px-1 pb-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setMonthCursor(addMonths(monthCursor, -1))}
            aria-label="Previous month"
            className="h-7 w-7 p-0"
          >
            <CaretLeft className="size-4" />
          </Button>
          <div className="type-size-14 font-medium select-none">
            {MONTHS[monthCursor.getMonth()]} {monthCursor.getFullYear()}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setMonthCursor(addMonths(monthCursor, 1))}
            aria-label="Next month"
            className="h-7 w-7 p-0"
          >
            <CaretRight className="size-4" />
          </Button>
        </div>

        {/* Weekday headers */}
        <div className="grid grid-cols-7 gap-1 px-1 type-size-10 text-muted-foreground">
          {"SMTWTFS".split("").map((ch, i) => (
            <div key={i} className="h-6 flex items-center justify-center select-none">
              {ch}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="mt-1 grid grid-cols-7 gap-y-0.5 touch-manipulation">
          {cal.map((cell) => {
            const isStart = visualStart && isSameDay(cell.date, visualStart);
            const isEnd = visualEnd && isSameDay(cell.date, visualEnd);
            const actualStart = visualStart && visualEnd && visualStart < visualEnd ? visualStart : visualEnd;
            const actualEnd = visualStart && visualEnd && visualStart < visualEnd ? visualEnd : visualStart;
            const inRange = actualStart && actualEnd
              ? isInRange(cell.date, actualStart, actualEnd)
              : false;
            const isRangeStart = actualStart && isSameDay(cell.date, actualStart);
            const isRangeEnd = actualEnd && isSameDay(cell.date, actualEnd);
            const isTod = isSameDay(cell.date, today);
            const isFuture = disableFuture && cell.date > today;
            const isSingleDay = isStart && isEnd;

            return (
              <div key={cell.key} className="relative h-8 flex items-center justify-center">
                {/* Background band for range - continuous across cells */}
                {inRange && !isSingleDay && (
                  <div
                    className={cn(
                      "absolute inset-y-0 bg-primary/10",
                      isRangeStart ? "left-1/2 right-0" : isRangeEnd ? "left-0 right-1/2" : "inset-x-0"
                    )}
                  />
                )}
                {/* The clickable date button */}
                <button
                  type="button"
                  onClick={() => !isFuture && handleDateClick(cell.date)}
                  onMouseEnter={() => selectionState === "selecting-end" && setHoveredDate(cell.date)}
                  onMouseLeave={() => setHoveredDate(null)}
                  disabled={isFuture}
                  className={cn(
                    "relative z-10 h-8 w-8 type-size-14 flex items-center justify-center transition-colors cursor-pointer select-none rounded-full",
                    cell.inMonth ? "" : "text-muted-foreground/40",
                    isFuture && "opacity-30 cursor-not-allowed",
                    // Start/end pill styling
                    (isRangeStart || isRangeEnd) && "bg-primary text-primary-foreground font-medium",
                    // Hover for non-selected dates
                    !isRangeStart && !isRangeEnd && !isFuture && "hover:bg-accent",
                    // Today indicator
                    isTod && !isRangeStart && !isRangeEnd && "ring-1 ring-ring/40"
                  )}
                  aria-label={`${cell.date.getFullYear()}-${pad(cell.date.getMonth() + 1)}-${pad(cell.date.getDate())}`}
                >
                  {cell.date.getDate()}
                </button>
              </div>
            );
          })}
        </div>

        {/* Current selection display */}
        {startSelected && endSelected && selectionState === "idle" && (
          <div className="mt-3 pt-3 border-t border-border/40 type-size-12 text-center text-muted-foreground">
            {fmtYmd(startSelected)} to {fmtYmd(endSelected)}
          </div>
        )}
      </Popover.Content>
    </Popover.Root>
  );
}

function buildCalendar(cursor: Date) {
  const first = startOfMonth(cursor);
  const last = endOfMonth(cursor);
  const startDay = first.getDay();
  const days = last.getDate();

  const cells: { key: string; date: Date; inMonth: boolean }[] = [];

  // Leading days from previous month
  for (let i = 0; i < startDay; i++) {
    const d = new Date(first);
    d.setDate(d.getDate() - (startDay - i));
    cells.push({ key: `p${i}` + d.getTime(), date: d, inMonth: false });
  }

  // Days in month
  for (let d = 1; d <= days; d++) {
    const dt = new Date(first.getFullYear(), first.getMonth(), d);
    cells.push({ key: `m${d}` + dt.getTime(), date: dt, inMonth: true });
  }

  // Trailing days to complete 6 rows (42 cells)
  const remaining = 42 - cells.length;
  for (let i = 0; i < remaining; i++) {
    const d = new Date(last);
    d.setDate(last.getDate() + (i + 1));
    cells.push({ key: `n${i}` + d.getTime(), date: d, inMonth: false });
  }

  return cells;
}

export default DateRangePicker;
