
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { listProjects, type ProjectWithConversationCount } from '@/lib/api/projects-core';
import { queryKeys } from '@/lib/query/query-keys';

export type ProjectsError = {
  message: string;
  status?: number;
};

function normalizeError(error: unknown): ProjectsError {
  if (!error) {
    return { message: 'Failed to load projects' };
  }
  if (typeof error === 'string') return { message: error };
  const baseMessage = (error as { message?: string }).message;
  return {
    message: typeof baseMessage === 'string' && baseMessage.trim().length > 0 ? baseMessage : 'Failed to load projects',
    status: typeof (error as { status?: number })?.status === 'number' ? (error as { status?: number }).status : undefined,
  };
}

export function useProjects() {
  const { isBackendAuthenticated, user } = useAuth();
  const queryClient = useQueryClient();

  const { data, error, isLoading, refetch } = useQuery<ProjectWithConversationCount[], Error>({
    queryKey: queryKeys.projects.list(user?.id ?? ''),
    queryFn: () => listProjects(),
    enabled: isBackendAuthenticated && !!user,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const refreshProjects = useCallback(() => refetch(), [refetch]);

  const updateProjects = useCallback((
    updater: (curr: ProjectWithConversationCount[]) => ProjectWithConversationCount[]
  ) => {
    queryClient.setQueryData(
      queryKeys.projects.list(user?.id ?? ''),
      (prev: ProjectWithConversationCount[] | undefined) => updater(prev ?? [])
    );
  }, [queryClient, user?.id]);

  const projects = data ?? [];

  return {
    projects,
    isLoading: isLoading && projects.length === 0,
    error: error ? normalizeError(error) : null,
    refreshProjects,
    updateProjects,
  };
}
