import {
  type JsonRecord,
  isRecord,
  expectRecord,
  readString,
  readNullableString,
} from "./contract-utils";
import { TOOL } from "@/lib/tools/constants";

export const INTERACTION_TYPES = ["user_input"] as const;

export type InteractiveToolName = typeof TOOL.REQUEST_USER_INPUT;
export type InteractiveToolType = (typeof INTERACTION_TYPES)[number];

export interface UserInputQuestionOptionPayload {
  label: string;
  description: string;
}

export interface UserInputQuestionPayload {
  id: string;
  question: string;
  options: UserInputQuestionOptionPayload[];
}

export interface RequestUserInputRequestPayload {
  tool: "request_user_input";
  title: string;
  prompt: string;
  questions: UserInputQuestionPayload[];
  custom_input_label?: string | null;
  submit_label?: string | null;
}

export interface UserInputAnswerPayload {
  question_id: string;
  option_label: string;
}

export interface RequestUserInputSubmissionPayload {
  answers: UserInputAnswerPayload[];
  custom_response?: string | null;
}

export interface RequestUserInputPendingResultPayload {
  status: "pending";
  interaction_type: "user_input";
  request: RequestUserInputRequestPayload;
}

export interface RequestUserInputCompletedResultPayload {
  status: "completed";
  interaction_type: "user_input";
  request: RequestUserInputRequestPayload;
  answers: UserInputAnswerPayload[];
  custom_response?: string | null;
}

export type RequestUserInputResultPayload =
  | RequestUserInputPendingResultPayload
  | RequestUserInputCompletedResultPayload;

export type InteractiveRequestPayload = RequestUserInputRequestPayload;
export type InteractiveResultPayload = RequestUserInputResultPayload;

export interface RequestUserInputPendingRequestResponse {
  call_id: string;
  tool_name: "request_user_input";
  request: RequestUserInputRequestPayload;
  result: RequestUserInputPendingResultPayload;
}

export type InteractivePendingRequestResponse = RequestUserInputPendingRequestResponse;

export interface RequestUserInputPendingRequestTransport {
  callId: string;
  toolName: "request_user_input";
  request: RequestUserInputRequestPayload;
  result: RequestUserInputPendingResultPayload;
}

export type InteractivePendingRequestTransport = RequestUserInputPendingRequestTransport;

function readRecordArray(record: JsonRecord, key: string, label: string): JsonRecord[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw new Error(`${label}.${key} must be an array`);
  }
  return value.filter((entry): entry is JsonRecord => isRecord(entry));
}

export function parseRequestUserInputRequestPayload(
  raw: unknown,
  label: string = "requestUserInputRequest",
): RequestUserInputRequestPayload {
  const record = expectRecord(raw, label);
  const tool = readString(record, "tool", label);
  if (tool !== "request_user_input") {
    throw new Error(`${label}.tool must be request_user_input`);
  }

  const questions = readRecordArray(record, "questions", label).map((entry, index) => {
    const questionLabel = `${label}.questions[${index}]`;
    const options = readRecordArray(entry, "options", questionLabel).map((option, optionIndex) => ({
      label: readString(option, "label", `${questionLabel}.options[${optionIndex}]`),
      description: readString(option, "description", `${questionLabel}.options[${optionIndex}]`),
    }));
    if (options.length < 2) {
      throw new Error(`${questionLabel}.options must contain at least two options`);
    }
    return {
      id: readString(entry, "id", questionLabel),
      question: readString(entry, "question", questionLabel),
      options,
    };
  });

  if (questions.length === 0) {
    throw new Error(`${label}.questions must contain at least one question`);
  }

  return {
    tool: "request_user_input",
    title: readString(record, "title", label),
    prompt: readString(record, "prompt", label),
    questions,
    custom_input_label: readNullableString(record, "custom_input_label"),
    submit_label: readNullableString(record, "submit_label"),
  };
}

export function parseRequestUserInputPendingResultPayload(
  raw: unknown,
  label: string = "requestUserInputPendingResult",
): RequestUserInputPendingResultPayload {
  const record = expectRecord(raw, label);
  if (readString(record, "status", label) !== "pending") {
    throw new Error(`${label}.status must be pending`);
  }
  if (readString(record, "interaction_type", label) !== "user_input") {
    throw new Error(`${label}.interaction_type must be user_input`);
  }
  return {
    status: "pending",
    interaction_type: "user_input",
    request: parseRequestUserInputRequestPayload(record.request, `${label}.request`),
  };
}

export function parseRequestUserInputCompletedResultPayload(
  raw: unknown,
  label: string = "requestUserInputCompletedResult",
): RequestUserInputCompletedResultPayload {
  const record = expectRecord(raw, label);
  if (readString(record, "status", label) !== "completed") {
    throw new Error(`${label}.status must be completed`);
  }
  if (readString(record, "interaction_type", label) !== "user_input") {
    throw new Error(`${label}.interaction_type must be user_input`);
  }

  const answersRaw = record.answers;
  if (!Array.isArray(answersRaw)) {
    throw new Error(`${label}.answers must be an array`);
  }

  return {
    status: "completed",
    interaction_type: "user_input",
    request: parseRequestUserInputRequestPayload(record.request, `${label}.request`),
    answers: answersRaw.map((entry, index) => {
      const answer = expectRecord(entry, `${label}.answers[${index}]`);
      return {
        question_id: readString(answer, "question_id", `${label}.answers[${index}]`),
        option_label: readString(answer, "option_label", `${label}.answers[${index}]`),
      };
    }),
    custom_response: readNullableString(record, "custom_response"),
  };
}

export function parseRequestUserInputResultPayload(
  raw: unknown,
  label: string = "requestUserInputResult",
): RequestUserInputResultPayload {
  const record = expectRecord(raw, label);
  const status = readString(record, "status", label);
  if (status === "pending") {
    return parseRequestUserInputPendingResultPayload(record, label);
  }
  if (status === "completed") {
    return parseRequestUserInputCompletedResultPayload(record, label);
  }
  throw new Error(`${label}.status must be pending or completed`);
}

export function parseInteractivePendingRequestResponse(
  raw: unknown,
  label: string = "interactivePendingRequest",
): InteractivePendingRequestResponse {
  const record = expectRecord(raw, label);
  const callId = readString(record, "call_id", label);
  const toolName = readString(record, "tool_name", label);
  if (toolName !== TOOL.REQUEST_USER_INPUT) {
    throw new Error(`${label}.tool_name must be request_user_input`);
  }
  return {
    call_id: callId,
    tool_name: TOOL.REQUEST_USER_INPUT,
    request: parseRequestUserInputRequestPayload(record.request, `${label}.request`),
    result: parseRequestUserInputPendingResultPayload(record.result, `${label}.result`),
  };
}

export function parseInteractivePendingRequestTransport(
  raw: unknown,
  label: string = "interactivePendingTransport",
): InteractivePendingRequestTransport {
  const record = expectRecord(raw, label);
  const callId = readString(record, "callId", label);
  const toolName = readString(record, "toolName", label);
  if (toolName !== TOOL.REQUEST_USER_INPUT) {
    throw new Error(`${label}.toolName must be request_user_input`);
  }
  return {
    callId,
    toolName: TOOL.REQUEST_USER_INPUT,
    request: parseRequestUserInputRequestPayload(record.request, `${label}.request`),
    result: parseRequestUserInputPendingResultPayload(record.result, `${label}.result`),
  };
}

export function toTransportPendingRequest(
  request: InteractivePendingRequestResponse,
): InteractivePendingRequestTransport {
  return {
    callId: request.call_id,
    toolName: TOOL.REQUEST_USER_INPUT,
    request: request.request,
    result: request.result,
  };
}

export function isRequestUserInputPendingRequestTransport(
  request: InteractivePendingRequestTransport,
): request is RequestUserInputPendingRequestTransport {
  return request.toolName === TOOL.REQUEST_USER_INPUT;
}
