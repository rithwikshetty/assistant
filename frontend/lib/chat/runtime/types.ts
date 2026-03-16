import type { ChatMessageContentPart } from "@/lib/chat/content-parts";
import type { StreamingStatusState } from "@/lib/chat/streaming-status";
import type { InteractivePendingRequestTransport } from "@/lib/contracts/chat-interactive";
import type {
  RunActivityPayload,
  RunActivityStatus,
  TimelineItemType,
  TimelineMessagePayload,
} from "@/lib/contracts/chat";

export type MessageContentPart = ChatMessageContentPart;

export type MessageMetadata = {
  event_type?: TimelineItemType;
  payload?: TimelineMessagePayload;
  run_id?: string | null;
  activity_item_count?: number;
  stream_checkpoint_event_id?: number | null;
  [key: string]: unknown;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: MessageContentPart[];
  activityItems?: RunActivityItem[];
  createdAt: Date;
  streamingStatus?: StreamingStatusState | null;
  metadata?: MessageMetadata;
  responseLatencyMs?: number | null;
  finishReason?: string | null;
  status?: TimelineMessagePayload["status"];
  userFeedbackId?: string | null;
  userFeedbackRating?: "up" | "down" | null;
  userFeedbackUpdatedAt?: string | null;
  suggestedQuestions?: string[] | null;
  attachments?: Array<{
    id: string;
    name: string;
    contentType?: string;
    fileSize?: number;
  }>;
};

export type UserInputPayload = {
  conversationId: string;
  runId?: string | null;
  messageId: string;
  requests: InteractivePendingRequestTransport[];
};

export type QueuedTurn = {
  queuePosition: number;
  runId: string;
  userMessageId: string;
  blockedByRunId: string | null;
  createdAt: string | null;
  text?: string | null;
};

export type RunActivityItem = {
  id: string;
  runId: string;
  itemKey: string;
  kind: "tool" | "reasoning" | "compaction" | "user_input";
  status: RunActivityStatus;
  title?: string | null;
  summary?: string | null;
  sequence: number;
  payload: RunActivityPayload;
  createdAt: string;
  updatedAt: string;
};

export type StreamPhase =
  | "idle"
  | "starting"
  | "streaming"
  | "paused_for_input"
  | "completing"
  | "error";

export type StreamSlice = {
  phase: StreamPhase;
  statusLabel: string | null;
  draftText: string;
  activityItems: RunActivityItem[];
  content: MessageContentPart[];
  liveMessage: Message | null;
  runId: string | null;
  runMessageId: string | null;
  assistantMessageId: string | null;
};

export type StreamDisplaySlice = {
  isStreaming: boolean;
  status: StreamingStatusState;
};

export type PagingSlice = {
  isLoadingInitial: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  error: Error | null;
};

export type TranscriptSlice = PagingSlice & {
  messages: Message[];
  nextCursor: string | null;
  initialized: boolean;
  lastSyncedAtMs: number;
};

export type InputGateSlice = {
  isPausedForInput: boolean;
  pausedPayload: UserInputPayload | null;
};

export type InputGateState = InputGateSlice;

export type RecheckAuthoritativeState = "running" | "paused" | "idle";

export type AuthoritativeStreamSnapshot = {
  status: RecheckAuthoritativeState;
  runId: string | null;
  runMessageId: string | null;
  currentStep: string | null;
  assistantMessageId: string | null;
  resumeSinceStreamEventId: number;
  activityCursor: number;
  pendingRequests: UserInputPayload["requests"];
  draftText: string;
  activityItems: RunActivityItem[];
  liveMessage: Message | null;
  queuedTurns: QueuedTurn[];
};

export type ConnectToStreamArgs = {
  sinceStreamEventId: number;
  draftText: string;
  activityItems: RunActivityItem[];
  runId: string | null;
  runMessageId: string | null;
  assistantMessageId?: string | null;
  statusLabel?: string | null;
  allowNoActiveRecheck?: boolean;
};

export type StreamRenderSlice = StreamSlice;

export type UseChatRuntimeReturn = {
  timeline: Message[];
  paging: PagingSlice;
  actions: {
    sendMessage: (
      content: string,
      options?: {
        attachmentIds?: string[];
        attachments?: Array<{ id: string; name: string; contentType?: string; fileSize?: number }>;
      }
    ) => Promise<void>;
    refresh: () => Promise<void>;
    loadOlderMessages: () => Promise<void>;
  };
};

export type UseChatOptions = {
  conversationId: string;
  onMessagesChange?: (messages: Message[]) => void;
  onError?: (error: Error) => void;
};
