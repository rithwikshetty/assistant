import { describe, expect, it } from "vitest";

import {
  parseChartToolResultPayload,
  parseGanttToolResultPayload,
} from "./chat-visible-tools";
import { parseToolResultPayloadForTool } from "./chat-tool-payloads";

describe("chat visible tool contracts", () => {
  it("parses canonical chart payloads", () => {
    expect(
      parseChartToolResultPayload({
        type: "bar",
        title: "Segment uplift",
        data: [
          { segment: "Baseline", uplift: 12.5 },
          { segment: "Stretch", uplift: 9.0 },
        ],
        config: {
          x_axis_key: "segment",
          data_keys: ["uplift"],
          x_axis_label: "Segment",
          y_axis_label: "Uplift (%)",
        },
      }),
    ).toMatchObject({
      type: "bar",
      title: "Segment uplift",
      config: {
        x_axis_key: "segment",
        data_keys: ["uplift"],
      },
    });
  });

  it("parses canonical gantt payloads", () => {
    expect(
      parseGanttToolResultPayload({
        title: "Tender programme",
        tasks: [
          {
            id: "task_1",
            name: "Scope review",
            start: "2026-03-01",
            end: "2026-03-05",
            progress: 50,
            custom_bar_color: "#001366",
          },
        ],
        view_mode: "Week",
        readonly: true,
      }),
    ).toMatchObject({
      title: "Tender programme",
      tasks: [{ id: "task_1", progress: 50 }],
      view_mode: "Week",
      readonly: true,
    });
  });

  it("rejects unsupported visible tools at the public entry point", () => {
    expect(() =>
      parseToolResultPayloadForTool("unknown_tool", {
        ok: true,
      }),
    ).toThrow("toolName must be a supported tool");
  });
});
