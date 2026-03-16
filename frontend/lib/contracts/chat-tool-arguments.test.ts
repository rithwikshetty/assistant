import { describe, expect, it } from "vitest";

import {
  parseQueryToolArguments,
  parseToolArgumentsPayloadForTool,
} from "./chat-tool-arguments";

describe("chat-tool-arguments", () => {
  it("parses canonical query tool arguments", () => {
    expect(
      parseQueryToolArguments({
        query: "latest uk construction inflation rates",
      }),
    ).toEqual({
      query: "latest uk construction inflation rates",
    });
  });

  it("dispatches arguments through the tool-aware contract edge", () => {
    expect(
      parseToolArgumentsPayloadForTool("load_skill", {
        skill_id: "cost-estimation",
      }),
    ).toEqual({
      skill_id: "cost-estimation",
    });
  });

  it("treats backend-supported retrieval tools as canonical query tools", () => {
    expect(
      parseToolArgumentsPayloadForTool("retrieval_web_search", {
        query: "hvac benchmark",
      }),
    ).toEqual({
      query: "hvac benchmark",
    });
  });

  it("accepts calculation tool arguments as structured records", () => {
    expect(
      parseToolArgumentsPayloadForTool("calc_unit_rate", {
        total_cost: "1000",
        quantity: "25",
        unit: "m2",
      }),
    ).toEqual({
      total_cost: "1000",
      quantity: "25",
      unit: "m2",
    });
  });
});
