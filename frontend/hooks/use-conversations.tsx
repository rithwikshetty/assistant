
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { getUserConversations, ConversationSummary, type ApiError } from '@/lib/api/auth';
import { reconcileConversationSummaries } from '@/lib/chat/conversation-list';
import { queryKeys } from '@/lib/query/query-keys';

export type ConversationsError = {
  message: string;
  status?: number;
  code?: string;
  detail?: string;
  retryAfterSeconds?: number;
};

function normalizeError(error: unknown): ConversationsError {
  if (!error) {
    return { message: 'Failed to load conversations' };
  }

  if (typeof error === 'string') {
    return { message: error };
  }

  const baseMessage = (error as { message?: string }).message;
  const typed = error as ApiError;

  return {
    message: typeof baseMessage === 'string' && baseMessage.trim().length > 0
      ? baseMessage
      : 'Failed to load conversations',
    status: typeof typed?.status === 'number' ? typed.status : undefined,
    code: typeof typed?.code === 'string' ? typed.code : undefined,
    detail: typeof typed?.detail === 'string' ? typed.detail : undefined,
    retryAfterSeconds: typeof typed?.retryAfterSeconds === 'number' ? typed.retryAfterSeconds : undefined,
  };
}

export function useConversations() {
  const { isBackendAuthenticated, user } = useAuth();
  const queryClient = useQueryClient();

  const { data, error, isLoading, refetch } = useQuery<ConversationSummary[], ApiError>({
    queryKey: queryKeys.conversations.list(user?.id ?? ''),
    queryFn: async () => {
      const conversations = await getUserConversations();
      const current =
        queryClient.getQueryData<ConversationSummary[]>(
          queryKeys.conversations.list(user?.id ?? ''),
        ) ?? [];
      return reconcileConversationSummaries(current, conversations);
    },
    enabled: isBackendAuthenticated && !!user,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    refetchOnWindowFocus: false,
    refetchOnReconnect: true,
  });

  const refreshConversations = useCallback(() => refetch(), [refetch]);

  const updateConversations = useCallback((
    updater: (curr: ConversationSummary[]) => ConversationSummary[]
  ) => {
    queryClient.setQueryData(
      queryKeys.conversations.list(user?.id ?? ''),
      (prev: ConversationSummary[] | undefined) => updater(prev ?? [])
    );
  }, [queryClient, user?.id]);

  const conversations = data ?? [];

  return {
    conversations,
    isLoading: isLoading && conversations.length === 0,
    error: error ? normalizeError(error) : null,
    refreshConversations,
    updateConversations,
  };
}
