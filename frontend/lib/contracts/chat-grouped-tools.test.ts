import { describe, expect, it } from "vitest";

import {
  parseCalculationResultPayload,
  parseKnowledgeResultPayload,
  parseTasksResultPayload,
  parseWebSearchResultPayload,
} from "./chat-grouped-tools";
import { parseToolResultPayloadForTool } from "./chat-tool-payloads";

describe("chat grouped tool contracts", () => {
  it("parses web search payloads", () => {
    expect(
      parseWebSearchResultPayload({
        content: "Summary",
        citations: [
          {
            index: 1,
            url: "https://example.com/article",
            title: "Example",
          },
        ],
      }),
    ).toMatchObject({
      content: "Summary",
      citations: [{ index: 1, url: "https://example.com/article" }],
    });
  });

  it("parses knowledge and calculation payloads", () => {
    expect(
      parseKnowledgeResultPayload({
        content: "Found references",
        query: "uk benchmarks",
        files: ["benchmarks.pdf"],
        results: [
          {
            file_id: "file_1",
            filename: "benchmarks.pdf",
            excerpts: ["QS benchmark excerpt"],
          },
        ],
      }),
    ).toMatchObject({
      query: "uk benchmarks",
      files: ["benchmarks.pdf"],
      results: [{ file_id: "file_1" }],
    });

    expect(
      parseCalculationResultPayload({
        operation: "calc_contingency",
        operation_label: "Contingency",
        result: { display: "£110,000.00", value: 110000 },
        details: [{ label: "Contingency Amount", value: "£10,000.00" }],
      }),
    ).toMatchObject({
      operation: "calc_contingency",
      result: { display: "£110,000.00" },
      details: [{ label: "Contingency Amount" }],
    });
  });

  it("parses tasks payloads and routes grouped tool dispatch through the public entry point", () => {
    expect(
      parseTasksResultPayload({
        action: "comment",
        task: {
          id: "task_1",
          title: "Review estimate",
        },
        comments: [
          {
            id: "comment_1",
            content: "Need market check",
          },
        ],
      }),
    ).toMatchObject({
      action: "comment",
      task: { id: "task_1", title: "Review estimate" },
      comments: [{ id: "comment_1", content: "Need market check" }],
    });

    expect(
      parseToolResultPayloadForTool("tasks", {
        action: "create",
        task: {
          id: "task_2",
          title: "Prepare clarifications",
        },
      }),
    ).toMatchObject({
      action: "create",
      task: { id: "task_2" },
    });
  });

  it("rejects unsupported grouped tools at the public entry point", () => {
    expect(() =>
      parseToolResultPayloadForTool("unknown_tool", {
        ok: true,
      }),
    ).toThrow("toolName must be a supported tool");
  });
});
