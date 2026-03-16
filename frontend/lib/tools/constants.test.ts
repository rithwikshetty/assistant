import { describe, expect, it } from "vitest";
import { CHAT_TOOL_NAMES } from "@/lib/chat/generated/ws-contract";

import {
  TOOL,
  TOOL_REGISTRY,
  getToolArgsSchemaKind,
  getToolDefinition,
  getToolDisplayName,
  getToolGroupKey,
  getToolRequestSchemaKind,
  getToolResultSchemaKind,
  isComposerInteractiveToolName,
  isKnowledgeToolName,
  isVisibleToolName,
} from "./constants";

describe("tool registry", () => {
  it("defines one canonical entry for every known tool name", () => {
    const toolNames = Object.values(TOOL);
    expect(new Set(toolNames).size).toBe(toolNames.length);
    expect([...CHAT_TOOL_NAMES].sort()).toEqual([...toolNames].sort());
    expect(Object.keys(TOOL_REGISTRY).sort()).toEqual([...toolNames].sort());

    for (const toolName of toolNames) {
      expect(getToolDefinition(toolName)).toMatchObject({
        name: toolName,
      });
      expect(getToolDisplayName(toolName)).not.toBe(toolName);
      expect(getToolArgsSchemaKind(toolName)).not.toBeNull();
      expect(getToolResultSchemaKind(toolName)).not.toBeNull();
    }
  });

  it("keeps visible tools centralized in the registry", () => {
    expect(isVisibleToolName(TOOL.CREATE_CHART)).toBe(true);
    expect(isVisibleToolName(TOOL.CREATE_GANTT)).toBe(true);
    expect(isVisibleToolName(TOOL.SEARCH_PROJECT_FILES)).toBe(false);
    expect(isVisibleToolName(TOOL.TASKS)).toBe(false);
    expect(isVisibleToolName(TOOL.REQUEST_USER_INPUT)).toBe(false);
  });

  it("marks grouped knowledge tools from the registry only", () => {
    expect(isKnowledgeToolName(TOOL.SEARCH_PROJECT_FILES)).toBe(true);
    expect(getToolGroupKey(TOOL.SEARCH_PROJECT_FILES)).toBe("KNOWLEDGE");
    expect(getToolGroupKey(TOOL.CALCULATE_UNIT_RATE)).toBe("CALCULATION");
  });

  it("keeps interactive request schema ownership in the registry", () => {
    expect(getToolRequestSchemaKind(TOOL.REQUEST_USER_INPUT)).toBe("requestUserInput");
    expect(isComposerInteractiveToolName(TOOL.REQUEST_USER_INPUT)).toBe(true);
    expect(isComposerInteractiveToolName(TOOL.EXECUTE_CODE)).toBe(false);
  });
});
