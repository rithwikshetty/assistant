export type ContentPhase = "worklog" | "final";

export type ChatMessageContentPart =
  | { type: "text"; text: string; phase?: ContentPhase }
  | { type: "divider"; label: string; source?: string; itemId?: string; phase?: ContentPhase }
  | {
      type: "tool-call";
      toolCallId: string;
      toolName: string;
      args?: Record<string, unknown>;
      result?: unknown;
      isError?: boolean;
      phase?: ContentPhase;
    }
  | {
      type: "reasoning";
      text: string;
      title?: string;
      rawText?: string;
      metadata?: Record<string, unknown>;
      phase?: ContentPhase;
    };
