/**
 * ToolCallPart - Renders individual tool call results
 */

import { type FC } from "react";
import { ExpandableToolResult } from "@/components/tools/expandable-tool-result";
import { VisibleToolRenderer } from "../tool-results/visible-tool-renderer";
import { TOOL } from "@/lib/tools/constants";
import {
  parseRequestUserInputResultPayload,
  type RequestUserInputResultPayload,
} from "@/lib/contracts/chat-interactive";
import { getToolDisplayName, getToolIcon, isVisibleTool } from "../utils";

type ToolCallPartProps = {
  toolName: string;
  toolCallId: string;
  args?: Record<string, unknown>;
  result?: unknown;
  isError?: boolean;
};

export const ToolCallPart: FC<ToolCallPartProps> = ({
  toolName,
  toolCallId,
  args,
  result,
  isError,
}) => {
  const part = {
    type: "tool-call" as const,
    toolName,
    toolCallId,
    args,
    result,
    isError,
  };

  if (isVisibleTool(toolName)) {
    return <VisibleToolRenderer part={part} />;
  }

  if (toolName === TOOL.REQUEST_USER_INPUT) {
    return <UserInputToolCallPart result={result} isError={isError} />;
  }

  const isComplete = result !== undefined;
  const isLoading = !isComplete && !isError;
  const toolLabel = getToolDisplayName(toolName);

  let body: string = "Running";
  if (isError) {
    body = "Tool execution failed";
  } else if (isComplete) {
    try {
      body = typeof result === "string" ? result : JSON.stringify(result, null, 2);
    } catch {
      body = String(result);
    }
  }

  return (
    <ExpandableToolResult
      icon={getToolIcon(toolName)}
      isLoading={isLoading}
      isComplete={isComplete}
      count={1}
      loadingLabel={`Running ${toolLabel}`}
      completeLabel={() => `${toolLabel} complete`}
      emptyLabel="No result"
      error={isError ? "Tool execution failed" : undefined}
      className="tool-connectable"
    >
      <pre className="type-size-13 max-h-[320px] overflow-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-2">
        {body}
      </pre>
    </ExpandableToolResult>
  );
};

// ============================================================================
// UserInputToolCallPart — nice summary for request_user_input results
// ============================================================================

const UserInputToolCallPart: FC<{ result?: unknown; isError?: boolean }> = ({
  result,
  isError,
}) => {
  const isComplete = result !== undefined;
  const isLoading = !isComplete && !isError;
  const parsedResult =
    result == null
      ? null
      : (() => {
          try {
            return parseRequestUserInputResultPayload(result, "toolCall.requestUserInputResult");
          } catch {
            return null;
          }
        })();

  return (
    <ExpandableToolResult
      icon={getToolIcon(TOOL.REQUEST_USER_INPUT)}
      isLoading={isLoading}
      isComplete={isComplete}
      count={isComplete ? 1 : 0}
      loadingLabel="Waiting for your input"
      completeLabel={() => "Gathering Input complete"}
      emptyLabel="No input received"
      error={isError ? "Input request failed" : undefined}
      className="tool-connectable"
    >
      {isComplete && <UserInputResultBody result={parsedResult} />}
    </ExpandableToolResult>
  );
};

const UserInputResultBody: FC<{ result: RequestUserInputResultPayload | null }> = ({ result }) => {
  if (!result) {
    return <p className="type-size-13 text-muted-foreground">Unable to parse input result</p>;
  }

  const questions = result.request?.questions;
  const answers = result.status === "completed" ? result.answers : [];
  const customResponse = result.status === "completed" ? result.custom_response : null;
  if (answers.length === 0 && !customResponse) {
    return <p className="type-size-13 text-muted-foreground">No answers provided</p>;
  }

  // Build a lookup from question_id → question text
  const questionMap = new Map<string, string>();
  if (Array.isArray(questions)) {
    for (const q of questions) {
      if (q.id && q.question) questionMap.set(q.id, q.question);
    }
  }

  return (
    <div className="space-y-1.5">
      {result.request?.title && (
        <p className="type-size-13 font-medium text-foreground">{result.request.title}</p>
      )}
      {answers.map((a, i) => (
        <div key={a.question_id || i} className="flex items-baseline gap-2">
          <span className="type-size-12 text-muted-foreground/50 shrink-0 tabular-nums w-3 text-right">{i + 1}</span>
          <div className="min-w-0">
            {questionMap.get(a.question_id || "") && (
              <span className="type-size-12 text-muted-foreground mr-1.5">
                {questionMap.get(a.question_id || "")}:
              </span>
            )}
            <span className="type-size-13 font-medium text-foreground">{a.option_label}</span>
          </div>
        </div>
      ))}
      {customResponse && (
        <p className="type-size-13 text-muted-foreground italic mt-1">{customResponse}</p>
      )}
    </div>
  );
};
