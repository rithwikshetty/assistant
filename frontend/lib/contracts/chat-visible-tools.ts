import {
  type JsonRecord,
  isRecord,
  expectRecord,
  readString,
  readNullableString,
  readNullableBoolean,
  readNullableNumber,
  readNullableStringArray,
  readRecordArray,
} from "./contract-utils";

export const CHART_TOOL_TYPES = [
  "bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "waterfall",
] as const;

export const GANTT_VIEW_MODES = ["Day", "Week", "Month", "Year"] as const;

export type ChartToolType = (typeof CHART_TOOL_TYPES)[number];
export type GanttViewMode = (typeof GANTT_VIEW_MODES)[number];

export interface ChartToolConfigPayload {
  x_axis_key?: string | null;
  data_keys?: string[] | null;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  colors?: string[] | null;
}

export interface ChartAutoRetryPayload {
  attempted: boolean;
  reason: "sparse_data";
  original_points: number;
  filtered_points: number;
}

export interface ChartToolResultPayload {
  type: ChartToolType;
  title: string;
  data: JsonRecord[];
  config?: ChartToolConfigPayload | null;
  auto_retry?: ChartAutoRetryPayload | null;
}

export interface GanttTaskPayload {
  id: string;
  name: string;
  start: string;
  end: string;
  progress?: number | null;
  dependencies?: string | null;
  custom_bar_color?: string | null;
}

export interface GanttToolResultPayload {
  title: string;
  tasks: GanttTaskPayload[];
  view_mode?: GanttViewMode | null;
  readonly?: boolean | null;
}

export type VisibleToolResultPayload =
  | ChartToolResultPayload
  | GanttToolResultPayload;

export function parseChartToolResultPayload(
  raw: unknown,
  label: string = "chartToolResult",
): ChartToolResultPayload {
  const record = expectRecord(raw, label);
  const type = readString(record, "type", label);
  if (!(CHART_TOOL_TYPES as readonly string[]).includes(type)) {
    throw new Error(`${label}.type must be one of: ${CHART_TOOL_TYPES.join(", ")}`);
  }

  const configRaw = record.config;
  const autoRetryRaw = record.auto_retry;
  return {
    type: type as ChartToolType,
    title: readString(record, "title", label),
    data: readRecordArray(record, "data", label),
    config: isRecord(configRaw)
      ? {
          x_axis_key: readNullableString(configRaw, "x_axis_key"),
          data_keys: readNullableStringArray(configRaw, "data_keys"),
          x_axis_label: readNullableString(configRaw, "x_axis_label"),
          y_axis_label: readNullableString(configRaw, "y_axis_label"),
          colors: readNullableStringArray(configRaw, "colors"),
        }
      : null,
    auto_retry: isRecord(autoRetryRaw)
      ? {
          attempted: (() => {
            const attempted = autoRetryRaw.attempted;
            if (typeof attempted !== "boolean") {
              throw new Error(`${label}.auto_retry.attempted must be a boolean`);
            }
            return attempted;
          })(),
          reason: (() => {
            const reason = readString(autoRetryRaw, "reason", `${label}.auto_retry`);
            if (reason !== "sparse_data") {
              throw new Error(`${label}.auto_retry.reason must be sparse_data`);
            }
            return "sparse_data" as const;
          })(),
          original_points: (() => {
            const points = readNullableNumber(autoRetryRaw, "original_points");
            if (points == null) {
              throw new Error(`${label}.auto_retry.original_points must be a number`);
            }
            return points;
          })(),
          filtered_points: (() => {
            const points = readNullableNumber(autoRetryRaw, "filtered_points");
            if (points == null) {
              throw new Error(`${label}.auto_retry.filtered_points must be a number`);
            }
            return points;
          })(),
        }
      : null,
  };
}

export function parseGanttToolResultPayload(
  raw: unknown,
  label: string = "ganttToolResult",
): GanttToolResultPayload {
  const record = expectRecord(raw, label);
  const viewMode = readNullableString(record, "view_mode");
  if (viewMode != null && !(GANTT_VIEW_MODES as readonly string[]).includes(viewMode)) {
    throw new Error(`${label}.view_mode must be one of: ${GANTT_VIEW_MODES.join(", ")}`);
  }

  return {
    title: readString(record, "title", label),
    tasks: readRecordArray(record, "tasks", label).map((task, index) => ({
      id: readString(task, "id", `${label}.tasks[${index}]`),
      name: readString(task, "name", `${label}.tasks[${index}]`),
      start: readString(task, "start", `${label}.tasks[${index}]`),
      end: readString(task, "end", `${label}.tasks[${index}]`),
      progress: readNullableNumber(task, "progress"),
      dependencies: readNullableString(task, "dependencies"),
      custom_bar_color: readNullableString(task, "custom_bar_color"),
    })),
    view_mode: viewMode as GanttViewMode | null | undefined,
    readonly: readNullableBoolean(record, "readonly"),
  };
}
