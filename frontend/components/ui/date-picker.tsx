
import * as React from "react";
import * as Popover from "@radix-ui/react-popover";
import { CaretLeft, CaretRight, CalendarBlank as CalendarIcon, X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
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
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
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

export interface DatePickerProps {
  id?: string;
  value: string; // YYYY-MM-DD or ""
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string; // extra classes for the trigger input
  clearable?: boolean;
}

export function DatePicker({ id, value, onChange, disabled, placeholder = "Select date", className, clearable = true }: DatePickerProps) {
  const today = React.useMemo(() => new Date(), []);
  const selected = parseYmd(value);
  const [open, setOpen] = React.useState(false);
  const [monthCursor, setMonthCursor] = React.useState<Date>(selected || startOfMonth(today));

  React.useEffect(() => {
    // When external value changes, move month to include it
    const sel = parseYmd(value);
    if (sel) setMonthCursor(startOfMonth(sel));
  }, [value]);

  const label = selected ? fmtHuman(selected) : "";

  function fmtHuman(d: Date) {
    const month = MONTHS[d.getMonth()].slice(0, 3);
    return `${month} ${d.getDate()}, ${d.getFullYear()}`;
  }

  const cal = buildCalendar(monthCursor);

  function selectDate(d: Date) {
    onChange(fmtYmd(d));
    setOpen(false);
  }

  function clear() {
    onChange("");
  }

  function quick(deltaDays: number) {
    const base = new Date();
    base.setDate(base.getDate() + deltaDays);
    selectDate(base);
  }

  return (
    <Popover.Root open={open} onOpenChange={(n) => { if (disabled) return; setOpen(n); }}>
      <Popover.Trigger asChild>
        <div className={cn("relative w-full", disabled && "pointer-events-none opacity-60") }>
          <Input
            id={id}
            value={label}
            onChange={() => {}}
            readOnly
            disabled={disabled}
            placeholder={placeholder}
            className={cn("pr-9 cursor-pointer", className)}
            aria-label="Choose date"
            onClick={() => !disabled && setOpen(true)}
          />
          <CalendarIcon className="absolute right-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" />
        </div>
      </Popover.Trigger>
      <Popover.Content align="start" sideOffset={6} className="z-[70] rounded-xl border bg-background shadow-xl w-[296px] p-3">
        <div className="flex items-center justify-between gap-2 px-1 pb-2">
          <div className="flex items-center gap-1">
            <Button type="button" variant="ghost" size="sm" onClick={() => setMonthCursor(addMonths(monthCursor, -1))} aria-label="Previous month">
              <CaretLeft className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setMonthCursor(addMonths(monthCursor, 1))} aria-label="Next month">
              <CaretRight className="size-4" />
            </Button>
          </div>
          <div className="type-size-14 font-medium select-none">
            {MONTHS[monthCursor.getMonth()]} {monthCursor.getFullYear()}
          </div>
          {clearable ? (
            <Button type="button" variant="ghost" size="sm" onClick={clear} aria-label="Clear date">
              <X className="size-4" />
            </Button>
          ) : (
            <div className="w-8" />
          )}
        </div>

        <div className="grid grid-cols-7 gap-1 px-1 type-size-10 text-muted-foreground">
          {"SMTWTFS".split("").map((ch, i) => (
            <div key={i} className="h-6 flex items-center justify-center select-none">
              {ch}
            </div>
          ))}
        </div>
        <div className="mt-1 grid grid-cols-7 gap-1">
          {cal.map((cell) => {
            const isSel = selected && isSameDay(cell.date, selected);
            const isTod = isSameDay(cell.date, today);
            return (
              <button
                key={cell.key}
                type="button"
                onClick={() => selectDate(cell.date)}
                className={cn(
                  "h-9 rounded-md type-size-14 flex items-center justify-center transition-colors cursor-pointer select-none",
                  cell.inMonth ? "" : "text-muted-foreground/50",
                  isSel ? "bg-primary text-primary-foreground" : "hover:bg-accent",
                  isTod && !isSel && "ring-1 ring-ring/40"
                )}
                aria-pressed={Boolean(isSel)}
                aria-label={`${cell.date.getFullYear()}-${pad(cell.date.getMonth() + 1)}-${pad(cell.date.getDate())}`}
              >
                {cell.date.getDate()}
              </button>
            );
          })}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button type="button" variant="outlined-md3" size="sm" onClick={() => quick(0)}>Today</Button>
          <Button type="button" variant="outlined-md3" size="sm" onClick={() => quick(1)}>Tomorrow</Button>
          <Button type="button" variant="outlined-md3" size="sm" onClick={() => quick(7)}>In 1 week</Button>
          <Button type="button" variant="outlined-md3" size="sm" onClick={() => setOpen(false)}>Close</Button>
        </div>
      </Popover.Content>
    </Popover.Root>
  );
}

function buildCalendar(cursor: Date) {
  const first = startOfMonth(cursor);
  const last = endOfMonth(cursor);
  const startDay = first.getDay(); // 0..6 (Sun..Sat)
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

export default DatePicker;
