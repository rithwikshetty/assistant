import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import {
  getProjectKnowledgeSummary,
  listProjectKnowledgeFiles,
  streamProjectKnowledgeProcessingStatus,
  type ProjectKnowledgeFileItem,
  type ProjectKnowledgeProcessingStatus,
  type ProjectKnowledgeSummaryResponse,
} from "@/lib/api/projects-core";
import { uploadStateManager } from "@/lib/upload-state-manager";

export type ProjectKnowledgeError = {
  message: string;
  status?: number;
};

type UseProjectKnowledgeOptions = {
  includeFiles?: boolean;
  pageSize?: number;
};

function normalizeError(error: unknown): ProjectKnowledgeError {
  if (!error) {
    return { message: "Failed to load project knowledge" };
  }

  if (typeof error === "string") {
    return { message: error };
  }

  const message = (error as { message?: string })?.message;
  const status = (error as { status?: number })?.status;

  return {
    message: typeof message === "string" && message.trim() ? message : "Failed to load project knowledge",
    status: typeof status === "number" ? status : undefined,
  };
}

const EMPTY_SUMMARY: ProjectKnowledgeSummaryResponse = {
  project_id: "",
  total_files: 0,
  total_size: 0,
  file_types: {},
  pending: 0,
  processing: 0,
  completed: 0,
  failed: 0,
  all_completed: true,
};

function statusSignature(value: Partial<ProjectKnowledgeProcessingStatus> | null | undefined): string {
  const total = Number(value?.total ?? 0);
  const pending = Number(value?.pending ?? 0);
  const processing = Number(value?.processing ?? 0);
  const completed = Number(value?.completed ?? 0);
  const failed = Number(value?.failed ?? 0);
  const allCompleted = value?.all_completed ? 1 : 0;
  return `${total}|${pending}|${processing}|${completed}|${failed}|${allCompleted}`;
}

async function reconcileProjectUploads(projectId: string): Promise<void> {
  const uploads = uploadStateManager
    .getUploads(projectId)
    .filter((upload) => upload.state === "processing" && upload.uploadedFileId);
  if (uploads.length === 0) {
    return;
  }

  const page = await listProjectKnowledgeFiles(projectId, { limit: 100, offset: 0 });
  const filesById = new Map<string, ProjectKnowledgeFileItem>();
  page.files.forEach((file) => {
    filesById.set(file.id, file);
  });

  uploads.forEach((upload) => {
    const fileId = upload.uploadedFileId;
    if (!fileId) {
      return;
    }
    const file = filesById.get(fileId);
    if (!file) {
      return;
    }
    if (file.processing_status === "completed") {
      uploadStateManager.updateUpload(upload.id, {
        state: "success",
        displayName: file.original_filename,
      });
      return;
    }
    if (file.processing_status === "failed") {
      uploadStateManager.updateUpload(upload.id, {
        state: "error",
        displayName: file.original_filename,
        error: file.processing_error || "Processing failed",
      });
    }
  });
}

export function useProjectKnowledge(projectId?: string | null, options?: UseProjectKnowledgeOptions) {
  const { isBackendAuthenticated, user } = useAuth();
  const queryClient = useQueryClient();
  const includeFiles = Boolean(options?.includeFiles);
  const pageSize = Math.max(1, Math.min(options?.pageSize ?? 50, 200));

  const queryKey = useMemo(
    () => ["project-knowledge-summary", projectId, user?.id] as const,
    [projectId, user?.id],
  );

  const { data, error, isLoading, refetch } = useQuery<ProjectKnowledgeSummaryResponse>({
    queryKey,
    queryFn: () => getProjectKnowledgeSummary(projectId as string),
    enabled: !!projectId && isBackendAuthenticated && !!user,
    staleTime: 2 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const [knowledge, setKnowledge] = useState<ProjectKnowledgeFileItem[]>([]);
  const [hasMoreFiles, setHasMoreFiles] = useState(false);
  const [nextOffset, setNextOffset] = useState<number | null>(0);
  const [isFilesLoading, setIsFilesLoading] = useState(false);
  const [isFetchingMore, setIsFetchingMore] = useState(false);

  const loadFilesPage = useCallback(
    async (offset: number, append: boolean) => {
      if (!projectId || !includeFiles) {
        setKnowledge([]);
        setHasMoreFiles(false);
        setNextOffset(0);
        return [];
      }

      if (append) {
        setIsFetchingMore(true);
      } else {
        setIsFilesLoading(true);
      }

      try {
        const page = await listProjectKnowledgeFiles(projectId, { limit: pageSize, offset });
        setKnowledge((current) => {
          if (!append) {
            return page.files;
          }
          const seen = new Set(current.map((file) => file.id));
          return [...current, ...page.files.filter((file) => !seen.has(file.id))];
        });
        setHasMoreFiles(page.has_more);
        setNextOffset(page.next_offset ?? null);
        return page.files;
      } finally {
        if (append) {
          setIsFetchingMore(false);
        } else {
          setIsFilesLoading(false);
        }
      }
    },
    [includeFiles, pageSize, projectId],
  );

  useEffect(() => {
    if (!includeFiles || !projectId || !isBackendAuthenticated || !user) {
      setKnowledge([]);
      setHasMoreFiles(false);
      setNextOffset(0);
      setIsFilesLoading(false);
      setIsFetchingMore(false);
      return;
    }
    void loadFilesPage(0, false);
  }, [includeFiles, isBackendAuthenticated, loadFilesPage, projectId, user]);

  const refresh = useCallback(async () => {
    const result = await refetch();
    if (includeFiles && projectId) {
      await loadFilesPage(0, false);
    }
    return result.data ?? null;
  }, [includeFiles, loadFilesPage, projectId, refetch]);

  const loadMoreFiles = useCallback(async () => {
    if (!includeFiles || !projectId || !hasMoreFiles || nextOffset == null || isFetchingMore) {
      return;
    }
    await loadFilesPage(nextOffset, true);
  }, [hasMoreFiles, includeFiles, isFetchingMore, loadFilesPage, nextOffset, projectId]);

  const response = data ?? (projectId ? { ...EMPTY_SUMMARY, project_id: projectId } : EMPTY_SUMMARY);
  const [liveProcessingStatus, setLiveProcessingStatus] = useState<ProjectKnowledgeProcessingStatus | null>(null);
  const lastStatusSignatureRef = useRef<string | null>(null);

  useEffect(() => {
    lastStatusSignatureRef.current = null;
    setLiveProcessingStatus(null);
  }, [projectId]);

  const hasSummaryProcessingFiles =
    Number(response.pending ?? 0) > 0 || Number(response.processing ?? 0) > 0;
  const hasLiveProcessingFiles =
    Number(liveProcessingStatus?.pending ?? 0) > 0 || Number(liveProcessingStatus?.processing ?? 0) > 0;

  useEffect(() => {
    if (!projectId || !isBackendAuthenticated || !user || !hasSummaryProcessingFiles) {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    const refreshAfterSettle = async () => {
      await refetch();
      if (includeFiles) {
        await loadFilesPage(0, false);
      }
      await reconcileProjectUploads(projectId);
    };

    const run = async () => {
      while (!cancelled) {
        let shouldReconnect = false;
        try {
          for await (const event of streamProjectKnowledgeProcessingStatus(projectId, { abortSignal: controller.signal })) {
            if (cancelled) return;

            if (event.type === "processing_status") {
              const payload = event.data as Partial<ProjectKnowledgeProcessingStatus> | undefined;
              const signature = statusSignature(payload);
              if (signature !== lastStatusSignatureRef.current) {
                lastStatusSignatureRef.current = signature;
                setLiveProcessingStatus(
                  payload
                    ? ({
                        project_id: String(payload.project_id ?? projectId),
                        total: Number(payload.total ?? 0),
                        pending: Number(payload.pending ?? 0),
                        processing: Number(payload.processing ?? 0),
                        completed: Number(payload.completed ?? 0),
                        failed: Number(payload.failed ?? 0),
                        all_completed: Boolean(payload.all_completed),
                      } satisfies ProjectKnowledgeProcessingStatus)
                    : null,
                );
              }
              continue;
            }

            if (event.type === "done") {
              setLiveProcessingStatus(null);
              await refreshAfterSettle();
              return;
            }

            if (event.type === "error") {
              shouldReconnect = true;
              break;
            }
          }
        } catch {
          if (controller.signal.aborted || cancelled) return;
          shouldReconnect = true;
        }

        if (!shouldReconnect || cancelled || controller.signal.aborted) {
          return;
        }

        const latest = await refetch();
        setLiveProcessingStatus(null);
        const latestSummary = latest.data;
        if (!latestSummary || ((latestSummary.pending ?? 0) <= 0 && (latestSummary.processing ?? 0) <= 0)) {
          await refreshAfterSettle();
          return;
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    };

    void run();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [hasSummaryProcessingFiles, includeFiles, isBackendAuthenticated, loadFilesPage, projectId, refetch, user]);

  const mutate = useCallback(
    (updater: (current: ProjectKnowledgeSummaryResponse) => ProjectKnowledgeSummaryResponse) => {
      queryClient.setQueryData<ProjectKnowledgeSummaryResponse>(queryKey, (current) => {
        const base = current ?? { ...EMPTY_SUMMARY, project_id: projectId ?? "" };
        return updater(base);
      });
    },
    [projectId, queryClient, queryKey],
  );

  return {
    response,
    summary: response,
    knowledge,
    totalFiles: response.total_files,
    totalSize: response.total_size,
    fileTypes: response.file_types,
    pendingCount: response.pending,
    processingCount: response.processing,
    failedCount: response.failed,
    hasProcessingFiles: hasSummaryProcessingFiles || hasLiveProcessingFiles,
    hasMoreFiles,
    isFetchingMore,
    isLoading:
      (isLoading && !data)
      || (includeFiles && isFilesLoading && response.total_files > 0 && knowledge.length === 0),
    error: error ? normalizeError(error) : null,
    refresh,
    loadMoreFiles,
    mutate,
  };
}
