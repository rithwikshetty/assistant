import { useEffect, useMemo } from "react";
import {
  useConversationInputGate,
  useConversationStream,
  useConversationTranscript,
  useConversationRuntimeManager,
} from "@/contexts/active-streams-context";
import { type ChatMessageContentPart } from "@/lib/chat/content-parts";
import {
  type StreamingPhase,
  type StreamingStatusState,
} from "@/lib/chat/streaming-status";
import type {
  UseChatOptions,
  UseChatRuntimeReturn,
} from "@/lib/chat/runtime/types";
import {
  buildStreamingTimeline,
} from "./use-chat-runtime.helpers";
import { resolveStreamDisplayState } from "./use-chat-runtime-display";

export type { Message, MessageContentPart, UseChatOptions, UseChatRuntimeReturn, UserInputPayload } from "@/lib/chat/runtime/types";
export type { StreamingPhase, StreamingStatusState };

export function useChat(options: UseChatOptions): UseChatRuntimeReturn {
  const { conversationId, onMessagesChange, onError } = options;
  const runtimeManager = useConversationRuntimeManager();
  const transcript = useConversationTranscript(conversationId);
  const stream = useConversationStream(conversationId);
  const inputGate = useConversationInputGate(conversationId);
  const allMessages = transcript.messages;

  useEffect(() => {
    runtimeManager.registerConversation(conversationId);
    return () => {
      runtimeManager.unregisterConversation(conversationId);
    };
  }, [conversationId, runtimeManager]);

  const streamDisplay = useMemo(() => {
    return resolveStreamDisplayState({
      stream,
      messages: allMessages,
      isPausedForInput: inputGate.isPausedForInput,
    });
  }, [allMessages, inputGate.isPausedForInput, stream]);

  const timeline = useMemo(() => {
    return buildStreamingTimeline({
      conversationId,
      messages: allMessages,
      stream,
      streamDisplay,
      isPausedForInput: inputGate.isPausedForInput,
    });
  }, [allMessages, conversationId, inputGate.isPausedForInput, stream, streamDisplay]);

  useEffect(() => {
    onMessagesChange?.(timeline);
  }, [timeline, onMessagesChange]);

  useEffect(() => {
    if (transcript.error) {
      onError?.(transcript.error);
    }
  }, [onError, transcript.error]);

  return {
    timeline,
    paging: {
      isLoadingInitial: transcript.isLoadingInitial,
      hasMore: transcript.hasMore,
      isLoadingMore: transcript.isLoadingMore,
      error: transcript.error,
    },
    actions: {
      sendMessage: (content, sendOptions) => runtimeManager.sendMessage(conversationId, content, sendOptions),
      refresh: () => runtimeManager.refreshConversation(conversationId),
      loadOlderMessages: () => runtimeManager.loadOlderMessages(conversationId),
    },
  };
}

export type { ChatMessageContentPart };
