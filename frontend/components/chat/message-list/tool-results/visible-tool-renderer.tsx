/**
 * VisibleToolRenderer - Renders the current contract's directly visible tools.
 */

import { lazy, Suspense, type FC } from "react";
import { ChartBar, ChartBarHorizontal } from "@phosphor-icons/react";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import { TOOL } from "@/lib/tools/constants";
import type { MessageContentPart } from "../types";
import { getToolDisplayName, getToolIcon } from "../utils";
import {
  parseChartToolResultPayload,
  parseGanttToolResultPayload,
  type GanttToolResultPayload,
} from "@/lib/contracts/chat-visible-tools";

const InlineChart = lazy(() =>
  import("@/components/chat/inline-chart").then((m) => ({ default: m.InlineChart })),
);

const InlineGanttEditable = lazy(() =>
  import("@/components/chat/inline-gantt-editable").then((m) => ({ default: m.InlineGanttEditable })),
);

type VisibleToolRendererProps = {
  part: MessageContentPart & { type: "tool-call" };
  messageId?: string;
  conversationId?: string;
  isFormStale?: boolean;
};

export const VisibleToolRenderer: FC<VisibleToolRendererProps> = ({
  part,
  messageId: _messageId,
  conversationId: _conversationId,
  isFormStale: _isFormStale = false,
}) => {
  const { toolName, result, isError } = part;

  if (isError || !result) {
    const loadingLabel =
      toolName === TOOL.CREATE_GANTT ? "Creating Gantt chart" : "Creating chart";
    const icon = toolName === TOOL.CREATE_GANTT ? ChartBarHorizontal : ChartBar;

    return (
      <ExpandableToolResult
        icon={icon}
        isLoading={!result && !isError}
        isComplete={!!result || !!isError}
        count={0}
        loadingLabel={loadingLabel}
        completeLabel={() => `${getToolDisplayName(toolName)} ${isError ? "failed" : "complete"}`}
        emptyLabel={isError ? "Tool execution failed" : "No result"}
        error={isError ? "Tool execution failed" : undefined}
        className="tool-connectable visible-tool w-full min-w-0"
      >
        <div className="type-size-14 text-muted-foreground">
          {isError ? "Tool execution failed" : "Loading"}
        </div>
      </ExpandableToolResult>
    );
  }

  switch (toolName) {
    case TOOL.CREATE_CHART: {
      try {
        const chartResult = parseChartToolResultPayload(result, "visibleTool.chartResult");
        return (
          <div className="tool-connectable visible-tool w-full min-w-0">
            <Suspense fallback={<div className="h-64 w-full animate-pulse rounded-lg bg-muted/40" />}>
              <InlineChart chartData={chartResult as Parameters<typeof InlineChart>[0]["chartData"]} />
            </Suspense>
          </div>
        );
      } catch {
        return (
          <ExpandableToolResult
            icon={ChartBar}
            isLoading={false}
            isComplete={true}
            count={0}
            loadingLabel="Creating chart"
            completeLabel={() => "Chart creation incomplete"}
            emptyLabel="Chart data unavailable"
            error="Chart data unavailable"
            className="tool-connectable visible-tool w-full min-w-0"
          >
            <div className="type-size-14 text-muted-foreground">
              The chart tool returned an unexpected payload, so no chart could be rendered.
            </div>
          </ExpandableToolResult>
        );
      }
    }
    case TOOL.CREATE_GANTT: {
      try {
        return <GanttDisplay result={parseGanttToolResultPayload(result, "visibleTool.ganttResult")} />;
      } catch {
        return null;
      }
    }
    default:
      return (
        <ExpandableToolResult
          icon={getToolIcon(toolName)}
          isLoading={false}
          isComplete={true}
          count={0}
          loadingLabel={`Creating ${getToolDisplayName(toolName)}`}
          completeLabel={() => `${getToolDisplayName(toolName)} unsupported`}
          emptyLabel="Tool output unavailable"
          error="Tool output unavailable"
          className="tool-connectable visible-tool w-full min-w-0"
        >
          <div className="type-size-14 text-muted-foreground">
            This tool is not renderable in the current frontend contract.
          </div>
        </ExpandableToolResult>
      );
  }
};

type GanttDisplayProps = {
  result: GanttToolResultPayload;
};

const GanttDisplay: FC<GanttDisplayProps> = ({ result }) => {
  return (
    <div className="tool-connectable visible-tool w-full min-w-0">
      <Suspense fallback={<div className="h-64 w-full animate-pulse rounded-lg bg-muted/40" />}>
        <InlineGanttEditable
          spec={{
            title: result.title || "Gantt Chart",
            tasks: result.tasks as Parameters<typeof InlineGanttEditable>[0]["spec"]["tasks"],
            view_mode: result.view_mode ?? undefined,
            readonly: true,
          }}
        />
      </Suspense>
    </div>
  );
};
