
import { useMemo, useCallback, type ReactElement } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  AreaChart,
  Area,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  Legend,
} from "recharts";
import { CHART_FONT_SIZES } from "@/lib/typography";
import { SafeResponsiveContainer } from "@/components/ui/safe-responsive-container";

type ChartData = {
  id?: string;
  type: string;
  title: string;
  data: Array<Record<string, string | number | boolean>>;
  config?: {
    x_axis_key?: string;
    data_keys?: string[];
    x_axis_label?: string;
    y_axis_label?: string;
    colors?: string[];
  };
};

type InlineChartProps = {
  chartData: ChartData;
};

// Default color palette for inline charts
const DEFAULT_COLORS = [
  "#2563eb", // Blue
  "#22c55e", // Green
  "#f97316", // Orange
  "#a855f7", // Purple
  "#ec4899", // Pink
  "#14b8a6", // Teal
  "#facc15", // Yellow
  "#ef4444", // Red
  "#6366f1", // Indigo
  "#0ea5e9", // Sky
];

// Stable default values to prevent recreation
const EMPTY_DATA: Array<Record<string, string | number | boolean>> = [];
const EMPTY_CONFIG: ChartData["config"] = {};
const DEFAULT_DATA_KEYS = ["value"];

// Stable bar radius values to prevent re-render loops
const BAR_RADIUS_TOP = [4, 4, 0, 0] as [number, number, number, number];
const BAR_RADIUS_NONE = [0, 0, 0, 0] as [number, number, number, number];

type ChartSurfaceProps = {
  children: ReactElement<{ width?: number; height?: number }>;
};

function ChartSurface({ children }: ChartSurfaceProps) {
  return (
    <SafeResponsiveContainer className="h-[320px] max-w-3xl overflow-visible">
      {children}
    </SafeResponsiveContainer>
  );
}

export function InlineChart({ chartData }: InlineChartProps) {
  const chartType = chartData.type || "bar";
  const title = chartData.title || "Chart";

  // Use stable defaults to prevent recreating arrays/objects
  const data = chartData.data || EMPTY_DATA;
  const config = (chartData.config || EMPTY_CONFIG) as NonNullable<ChartData["config"]>;
  const xAxisKey = config.x_axis_key || "name";
  const dataKeys = config.data_keys || DEFAULT_DATA_KEYS;
  const colors = config.colors || DEFAULT_COLORS;
  const hasXAxisLabel = Boolean(config.x_axis_label?.trim());
  const hasYAxisLabel = Boolean(config.y_axis_label?.trim());

  // Use fixed gray color that works in both light and dark modes
  const axisColor = "#888888";

  const chartMargin = useMemo(
    () => ({
      top: 28,
      right: 24,
      bottom: hasXAxisLabel ? 56 : 40,
      left: hasYAxisLabel ? 42 : 6,
    }),
    [hasXAxisLabel, hasYAxisLabel],
  );
  const yAxisWidth = hasYAxisLabel ? 44 : 36;
  const axisLabelStyle = useMemo(
    () => ({ fill: axisColor, fontSize: CHART_FONT_SIZES.axisLabel }),
    [axisColor],
  );
  const tickStyle = useMemo(
    () => ({ fill: axisColor, fontSize: CHART_FONT_SIZES.axisTick }),
    [axisColor],
  );

  const compactFormatter = useMemo(
    () =>
      new Intl.NumberFormat("en-GB", {
        notation: "compact",
        compactDisplay: "short",
        maximumFractionDigits: 1,
      }),
    [],
  );
  const integerFormatter = useMemo(
    () =>
      new Intl.NumberFormat("en-GB", {
        maximumFractionDigits: 0,
      }),
    [],
  );
  const preciseFormatter = useMemo(
    () =>
      new Intl.NumberFormat("en-GB", {
        maximumFractionDigits: 2,
      }),
    [],
  );

  const formatNumericValue = useCallback(
    (value: number): string => {
      if (!Number.isFinite(value)) {
        return String(value);
      }
      const absValue = Math.abs(value);
      // Use compact notation for 5+ digits (10,000+)
      if (absValue >= 10_000) {
        return compactFormatter.format(value);
      }
      // Use integer format for 4 digits (1,000-9,999)
      if (absValue >= 1_000) {
        return integerFormatter.format(value);
      }
      // Use precise format for smaller numbers
      return preciseFormatter.format(value);
    },
    [compactFormatter, integerFormatter, preciseFormatter],
  );

  const yAxisTickFormatter = useCallback(
    (tick: string | number): string => (typeof tick === "number" ? formatNumericValue(tick) : String(tick)),
    [formatNumericValue],
  );

  const tooltipValueFormatter = useCallback(
    (value: string | number): string => (typeof value === "number" ? formatNumericValue(value) : String(value)),
    [formatNumericValue],
  );

  // Memoize all Recharts component props to prevent re-render loops
  const legendWrapperStyle = useMemo(
    () => ({ color: "hsl(var(--foreground))", fontSize: CHART_FONT_SIZES.tooltip }),
    [],
  );

  const tooltipContentStyle = useMemo(
    () => ({
      backgroundColor: "hsl(var(--popover))",
      border: "1px solid hsl(var(--border))",
      borderRadius: "6px",
      fontSize: CHART_FONT_SIZES.tooltip,
    }),
    [],
  );

  const tooltipLabelStyle = useMemo(
    () => ({
      color: "hsl(var(--foreground))",
      fontWeight: 500,
      marginBottom: "4px",
    }),
    [],
  );

  const tooltipItemStyle = useMemo(
    () => ({
      color: "hsl(var(--popover-foreground))",
      fontSize: CHART_FONT_SIZES.tooltip,
      lineHeight: 1.5,
    }),
    [],
  );

  const tooltipCursorStyle = useMemo(
    () => ({ fill: "hsl(var(--muted))", opacity: 0.2 }),
    [],
  );

  const axisTickLineStyle = useMemo(() => ({ stroke: axisColor }), [axisColor]);
  const axisLineStyle = useMemo(() => ({ stroke: axisColor }), [axisColor]);

  // Waterfall chart data transformation (always computed, only used if chartType === "waterfall")
  const waterfallData = useMemo(() => {
    if (chartType !== "waterfall") return [];

    let cumulative = 0;
    const valueKey = dataKeys[0] || "value";

    return data.map((item) => {
      const value = typeof item[valueKey] === "number" ? item[valueKey] : 0;
      const isTotal = item.isTotal === true || item.is_total === true;

      let start: number;
      let end: number;

      if (isTotal) {
        // Total bars start from 0
        start = 0;
        end = cumulative + value;
        cumulative = end;
      } else {
        // Regular bars show change
        start = cumulative;
        end = cumulative + value;
        cumulative = end;
      }

      return {
        ...item,
        start,
        value: Math.abs(value),
        end,
        isIncrease: value >= 0,
        isTotal,
        originalValue: value,
      };
    });
  }, [chartType, data, dataKeys]);

  const waterfallColors = useMemo(
    () => ({
      increase: colors[1] || "#22c55e", // Green
      decrease: colors[7] || "#ef4444", // Red
      total: colors[0] || "#2563eb", // Blue
    }),
    [colors]
  );

  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[300px] type-size-14 text-muted-foreground">
        No data to display
      </div>
    );
  }

  // Pie chart - single series only
  if (chartType === "pie") {
    const pieData = data.map((item) => ({
      name: item[xAxisKey],
      value: item[dataKeys[0]] || 0,
    }));

    const renderPieLabel = (props: {
      cx?: string | number;
      cy?: string | number;
      midAngle?: number;
      outerRadius?: string | number;
      name?: string;
      percent?: number;
    }) => {
      const { cx, cy, midAngle, outerRadius, name, percent } = props;
      if (!cx || !cy || midAngle === undefined || !outerRadius || !name || percent === undefined) {
        return null;
      }
      const RADIAN = Math.PI / 180;
      const cxNum = Number(cx);
      const cyNum = Number(cy);
      const radius = Number(outerRadius) + 25;
      const x = cxNum + radius * Math.cos(-midAngle * RADIAN);
      const y = cyNum + radius * Math.sin(-midAngle * RADIAN);

      return (
        <text
          x={x}
          y={y}
          fill={axisColor}
          textAnchor={x > cxNum ? "start" : "end"}
          dominantBaseline="central"
          fontSize={12}
        >
          {`${name}: ${(percent * 100).toFixed(0)}%`}
        </text>
      );
    };

    return (
      <div className="space-y-4">
        <h3 className="type-size-16 font-semibold text-foreground">{title}</h3>
        <ChartSurface>
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={100}
                paddingAngle={2}
                label={renderPieLabel}
                isAnimationActive={false}
              >
                {pieData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={tooltipContentStyle}
                labelStyle={tooltipLabelStyle}
                itemStyle={tooltipItemStyle}
                formatter={(value: string | number, name: string) => [tooltipValueFormatter(value), name]}
              />
            </PieChart>
        </ChartSurface>
      </div>
    );
  }

  // Bar chart
  if (chartType === "bar") {
    return (
      <div className="space-y-4">
        <h3 className="type-size-16 font-semibold text-foreground">{title}</h3>
        <ChartSurface>
            <BarChart data={data} margin={chartMargin}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey={xAxisKey}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={8}
                label={
                  hasXAxisLabel
                    ? { value: config.x_axis_label, position: "bottom", offset: 24, style: axisLabelStyle }
                    : undefined
                }
              />
              <YAxis
                width={yAxisWidth}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={4}
                tickFormatter={yAxisTickFormatter}
                label={
                  hasYAxisLabel
                    ? { value: config.y_axis_label, angle: -90, position: "center", dx: -25, style: axisLabelStyle }
                    : undefined
                }
              />
              <Tooltip
                contentStyle={tooltipContentStyle}
                labelStyle={tooltipLabelStyle}
                itemStyle={tooltipItemStyle}
                cursor={tooltipCursorStyle}
                formatter={(value: string | number, name: string) => [tooltipValueFormatter(value), name]}
              />
              {dataKeys.length > 1 && (
                <Legend wrapperStyle={legendWrapperStyle} />
              )}
              {dataKeys.map((key, index) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={colors[index % colors.length]}
                  radius={BAR_RADIUS_TOP}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
        </ChartSurface>
      </div>
    );
  }

  // Stacked Bar chart
  if (chartType === "stacked_bar") {
    return (
      <div className="space-y-4">
        <h3 className="type-size-16 font-semibold text-foreground">{title}</h3>
        <ChartSurface>
            <BarChart data={data} margin={chartMargin}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey={xAxisKey}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={8}
                label={
                  hasXAxisLabel
                    ? { value: config.x_axis_label, position: "bottom", offset: 24, style: axisLabelStyle }
                    : undefined
                }
              />
              <YAxis
                width={yAxisWidth}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={4}
                tickFormatter={yAxisTickFormatter}
                label={
                  hasYAxisLabel
                    ? { value: config.y_axis_label, angle: -90, position: "center", dx: -25, style: axisLabelStyle }
                    : undefined
                }
              />
              <Tooltip
                contentStyle={tooltipContentStyle}
                labelStyle={tooltipLabelStyle}
                itemStyle={tooltipItemStyle}
                cursor={tooltipCursorStyle}
                formatter={(value: string | number, name: string) => [tooltipValueFormatter(value), name]}
              />
              {dataKeys.length > 1 && (
                <Legend wrapperStyle={legendWrapperStyle} />
              )}
              {dataKeys.map((key, index) => (
                <Bar
                  key={key}
                  dataKey={key}
                  stackId="stack"
                  fill={colors[index % colors.length]}
                  radius={index === dataKeys.length - 1 ? BAR_RADIUS_TOP : BAR_RADIUS_NONE}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
        </ChartSurface>
      </div>
    );
  }

  // Line chart
  if (chartType === "line") {
    return (
      <div className="space-y-4">
        <h3 className="type-size-16 font-semibold text-foreground">{title}</h3>
        <ChartSurface>
            <LineChart data={data} margin={chartMargin}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey={xAxisKey}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={8}
                label={
                  hasXAxisLabel
                    ? { value: config.x_axis_label, position: "bottom", offset: 24, style: axisLabelStyle }
                    : undefined
                }
              />
              <YAxis
                width={yAxisWidth}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={4}
                tickFormatter={yAxisTickFormatter}
                label={
                  hasYAxisLabel
                    ? { value: config.y_axis_label, angle: -90, position: "center", dx: -25, style: axisLabelStyle }
                    : undefined
                }
              />
              <Tooltip
                contentStyle={tooltipContentStyle}
                labelStyle={tooltipLabelStyle}
                itemStyle={tooltipItemStyle}
                formatter={(value: string | number, name: string) => [tooltipValueFormatter(value), name]}
              />
              {dataKeys.length > 1 && (
                <Legend wrapperStyle={legendWrapperStyle} />
              )}
              {dataKeys.map((key, index) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={colors[index % colors.length]}
                  strokeWidth={2}
                  dot={{ fill: colors[index % colors.length], r: 4 }}
                  activeDot={{ r: 6 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
        </ChartSurface>
      </div>
    );
  }

  // Area chart
  if (chartType === "area") {
    return (
      <div className="space-y-4">
        <h3 className="type-size-16 font-semibold text-foreground">{title}</h3>
        <ChartSurface>
            <AreaChart data={data} margin={chartMargin}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey={xAxisKey}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={8}
                label={
                  hasXAxisLabel
                    ? { value: config.x_axis_label, position: "bottom", offset: 24, style: axisLabelStyle }
                    : undefined
                }
              />
              <YAxis
                width={yAxisWidth}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={4}
                tickFormatter={yAxisTickFormatter}
                label={
                  hasYAxisLabel
                    ? { value: config.y_axis_label, angle: -90, position: "center", dx: -25, style: axisLabelStyle }
                    : undefined
                }
              />
              <Tooltip
                contentStyle={tooltipContentStyle}
                labelStyle={tooltipLabelStyle}
                itemStyle={tooltipItemStyle}
                formatter={(value: string | number, name: string) => [tooltipValueFormatter(value), name]}
              />
              {dataKeys.length > 1 && (
                <Legend wrapperStyle={legendWrapperStyle} />
              )}
              {dataKeys.map((key, index) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  fill={colors[index % colors.length]}
                  stroke={colors[index % colors.length]}
                  fillOpacity={0.6}
                  isAnimationActive={false}
                />
              ))}
            </AreaChart>
        </ChartSurface>
      </div>
    );
  }

  // Waterfall chart
  if (chartType === "waterfall") {

    return (
      <div className="space-y-4">
        <h3 className="type-size-16 font-semibold text-foreground">{title}</h3>
        <ChartSurface>
            <ComposedChart data={waterfallData} margin={chartMargin}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey={xAxisKey}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={8}
                label={
                  hasXAxisLabel
                    ? { value: config.x_axis_label, position: "bottom", offset: 24, style: axisLabelStyle }
                    : undefined
                }
              />
              <YAxis
                width={yAxisWidth}
                tick={tickStyle}
                tickLine={axisTickLineStyle}
                axisLine={axisLineStyle}
                tickMargin={4}
                tickFormatter={yAxisTickFormatter}
                label={
                  hasYAxisLabel
                    ? { value: config.y_axis_label, angle: -90, position: "center", dx: -25, style: axisLabelStyle }
                    : undefined
                }
              />
              <Tooltip
                contentStyle={tooltipContentStyle}
                labelStyle={tooltipLabelStyle}
                itemStyle={tooltipItemStyle}
                cursor={tooltipCursorStyle}
                formatter={(value: string | number, name: string, props: { payload?: { originalValue?: number } }) => {
                  if (name === "start") return null; // Hide invisible base bar
                  const originalValue = props.payload?.originalValue;
                  if (typeof originalValue === "number") {
                    return [formatNumericValue(originalValue), "Change"];
                  }
                  return [tooltipValueFormatter(value), name];
                }}
              />
              {/* Invisible base bar to position the visible bars */}
              <Bar dataKey="start" stackId="waterfall" fill="transparent" isAnimationActive={false} />
              {/* Visible change bar with dynamic colors */}
              <Bar dataKey="value" stackId="waterfall" radius={BAR_RADIUS_TOP} isAnimationActive={false}>
                {waterfallData.map((entry, index) => {
                  let fillColor: string;
                  if (entry.isTotal) {
                    fillColor = waterfallColors.total;
                  } else if (entry.isIncrease) {
                    fillColor = waterfallColors.increase;
                  } else {
                    fillColor = waterfallColors.decrease;
                  }
                  return <Cell key={`cell-${index}`} fill={fillColor} />;
                })}
              </Bar>
            </ComposedChart>
        </ChartSurface>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-[300px] type-size-14 text-muted-foreground">
      Unsupported chart type: {chartType}
    </div>
  );
}
