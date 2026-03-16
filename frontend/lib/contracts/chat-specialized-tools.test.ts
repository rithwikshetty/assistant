import { describe, expect, it } from "vitest";

import {
  parseExecuteCodeResultPayload,
  parseFileReadResultPayload,
  parseSkillResultPayload,
} from "./chat-specialized-tools";
import { parseToolResultPayloadForTool } from "./chat-tool-payloads";

describe("chat specialized tool contracts", () => {
  it("parses file-read and execute-code payloads", () => {
    expect(
      parseFileReadResultPayload({
        file_id: "file_1",
        filename: "report.pdf",
        chunks: [{ content: "Executive summary", chunk_start: 0, chunk_end: 17 }],
        total_length: 17,
      }),
    ).toMatchObject({
      file_id: "file_1",
      chunks: [{ content: "Executive summary" }],
    });

    expect(
      parseExecuteCodeResultPayload({
        success: true,
        execution_time_ms: 420,
        stdout: "ok",
        generated_files: [{ file_id: "file_2", filename: "output.csv" }],
      }),
    ).toMatchObject({
      success: true,
      stdout: "ok",
      generated_files: [{ file_id: "file_2" }],
    });
  });

  it("parses skill payloads", () => {
    expect(
      parseSkillResultPayload({
        skill_id: "cost-estimation",
        name: "Cost Estimation",
        content: "# Cost Estimation",
        available_modules: ["references/module_a"],
      }),
    ).toMatchObject({
      skill_id: "cost-estimation",
      name: "Cost Estimation",
      available_modules: ["references/module_a"],
    });
  });

  it("rejects unsupported specialized tools at the public entry point", () => {
    expect(() =>
      parseToolResultPayloadForTool("unknown_tool", {
        ok: true,
      }),
    ).toThrow("toolName must be a supported tool");
  });
});
