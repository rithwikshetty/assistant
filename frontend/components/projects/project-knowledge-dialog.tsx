
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjectKnowledge } from "@/hooks/use-project-knowledge";
import { useAuth } from "@/contexts/auth-context";
import {
  createProjectKnowledgeArchiveJob,
  deleteProjectKnowledgeFile,
  deleteAllProjectKnowledgeFiles,
  getProjectKnowledgeArchiveJob,
  uploadProjectKnowledgeFile,
  type ProjectKnowledgeFileItem,
} from "@/lib/api/projects-core";
import { getFileDownloadUrl } from "@/lib/api/files";
import { formatBytes } from "@/lib/attachments";
import { cn } from "@/lib/utils";
import { Warning, DownloadSimple, FileText, SpinnerGap, ArrowsClockwise, Trash, CloudArrowUp, X, CheckCircle, XCircle } from "@phosphor-icons/react";
import { uploadStateManager, type FileUploadItem } from "@/lib/upload-state-manager";
import {
  FILE_ACCEPT_STRING,
  ALLOWED_FORMATS_DISPLAY,
  isAllowedFile as checkIfFileAllowed,
  MAX_FILE_SIZE_BYTES,
} from "@/lib/file-types";
import { FileUploadWarningDialog } from "@/components/ui/file-upload-warning-dialog";

interface ProjectKnowledgeDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string | null;
  projectName?: string | null;
  canManageKnowledge?: boolean;
  canUploadKnowledge?: boolean;
  isPublicProject?: boolean;
}

export function ProjectKnowledgeDialog({
  open,
  onClose,
  projectId,
  projectName,
  canManageKnowledge,
  canUploadKnowledge,
  isPublicProject,
}: ProjectKnowledgeDialogProps) {
  const effectiveProjectId = open ? projectId : null;
  const { addToast } = useToast();
  const {
    knowledge,
    isLoading,
    isFetchingMore,
    hasMoreFiles,
    hasProcessingFiles,
    loadMoreFiles,
    error,
    refresh,
    totalFiles,
    totalSize,
    fileTypes,
  } = useProjectKnowledge(effectiveProjectId, { includeFiles: open, pageSize: 50 });
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [activeUploads, setActiveUploads] = useState<FileUploadItem[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingAll, setDeletingAll] = useState(false);
  const [downloadingAll, setDownloadSimpleingAll] = useState(false);
  const [downloadingId, setDownloadSimpleingId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [uploadsExpanded, setUploadsExpanded] = useState(false);
  const [showFileWarningDialog, setShowFileWarningDialog] = useState(false);
  const [redactionEnabled, setRedactionEnabled] = useState(false);
  const { user } = useAuth();
  const currentUserId = user?.id ?? null;
  const currentUserEmail = user?.email ? user.email.toLowerCase() : null;
  const canManageAllFiles = Boolean(canManageKnowledge);
  const allowKnowledgeUpload = canUploadKnowledge ?? true;
  const uploadRestrictionMessage = !allowKnowledgeUpload
    ? isPublicProject
      ? "Only the project owner can add knowledge base files to public projects."
      : "You don't have permission to add knowledge base files."
    : null;

  // Subscribe to upload state manager
  useEffect(() => {
    if (!projectId) return;
    const unsubscribe = uploadStateManager.subscribe((uploads) => {
      setActiveUploads(uploads.filter((u) => u.projectId === projectId));
    });
    return unsubscribe;
  }, [projectId]);

  const knowledgeIds = useMemo(() => new Set(knowledge.map((file) => file.id)), [knowledge]);
  const visibleUploads = useMemo(
    () =>
      activeUploads.filter((upload) => {
        if (upload.state === "error") return true;
        if (upload.state === "pending" || upload.state === "uploading") return true;
        if (!upload.uploadedFileId) return true;
        return !knowledgeIds.has(upload.uploadedFileId);
      }),
    [activeUploads, knowledgeIds],
  );
  const hasPendingUploads = activeUploads.some((u) => u.state === "pending" || u.state === "uploading");
  const hasTrackedProcessingUploads = activeUploads.some((u) => u.state === "processing");
  const hasActiveUploads = hasPendingUploads || hasTrackedProcessingUploads || hasProcessingFiles;
  const uploadButtonDisabled = hasPendingUploads || !projectId || !allowKnowledgeUpload;

  // Auto-clear completed uploads after a short delay (they show in the Files list)
  useEffect(() => {
    if (!projectId) return;
    const allSettled = activeUploads.length > 0 && activeUploads.every((u) => u.state === "success" || u.state === "error");
    if (!allSettled) return;
    const hasSuccess = activeUploads.some((u) => u.state === "success");
    if (!hasSuccess) return;
    const timer = setTimeout(() => {
      uploadStateManager.clearCompleted(projectId);
    }, 2000);
    return () => clearTimeout(timer);
  }, [activeUploads, projectId]);

  useEffect(() => {
    if (!open || !projectId || (!hasTrackedProcessingUploads && !hasProcessingFiles)) {
      return;
    }

    const interval = window.setInterval(() => {
      void refresh();
    }, 2000);

    return () => {
      window.clearInterval(interval);
    };
  }, [hasProcessingFiles, hasTrackedProcessingUploads, open, projectId, refresh]);

  useEffect(() => {
    if (!projectId || activeUploads.length === 0 || knowledge.length === 0) {
      return;
    }

    const knowledgeById = new Map(knowledge.map((file) => [file.id, file]));
    activeUploads.forEach((upload) => {
      if (!upload.uploadedFileId || (upload.state !== "processing" && upload.state !== "success")) {
        return;
      }

      const backendFile = knowledgeById.get(upload.uploadedFileId);
      if (!backendFile) {
        return;
      }

      if (backendFile.processing_status === "completed" && upload.state !== "success") {
        uploadStateManager.updateUpload(upload.id, { state: "success" });
      } else if (backendFile.processing_status === "failed") {
        uploadStateManager.updateUpload(upload.id, {
          state: "error",
          error: backendFile.processing_error || "Processing failed",
        });
      } else if (
        (backendFile.processing_status === "pending" || backendFile.processing_status === "processing") &&
        upload.state !== "processing"
      ) {
        uploadStateManager.updateUpload(upload.id, { state: "processing" });
      }
    });
  }, [activeUploads, knowledge, projectId]);
  const emptyStateHelpText = uploadRestrictionMessage ?? "Upload project documents to make them available in chats.";
  const showUploadControls = allowKnowledgeUpload;

  // File validation using centralized config
  const isAllowedFile = useCallback((file: File) => checkIfFileAllowed(file), []);

  // Clear only UI-specific state when dialog closes (keep upload state in manager)
  useEffect(() => {
    if (!open) {
      setDeletingId(null);
      setDownloadSimpleingId(null);
    }
  }, [open]);

  const canManageFile = useCallback(
    (file: ProjectKnowledgeFileItem) => {
      if (canManageAllFiles) return true;
      const uploaderId = file.uploaded_by?.id ?? null;
      if (uploaderId && currentUserId) {
        return uploaderId === currentUserId;
      }
      if (currentUserEmail) {
        const uploaderEmail = file.uploaded_by?.email?.toLowerCase() ?? null;
        if (uploaderEmail) {
          return uploaderEmail === currentUserEmail;
        }
      }
      return false;
    },
    [canManageAllFiles, currentUserEmail, currentUserId],
  );

  // No image-count limit; keep UI simple and aligned with backend

  // Load persisted redaction state on mount
  useEffect(() => {
    try {
      const fromSession = typeof window !== 'undefined' ? window.sessionStorage.getItem("assist:redactionEnabled") : null;
      const fromLocal = typeof window !== 'undefined' ? window.localStorage.getItem("assist:redactionEnabled") : null;
      const raw = fromSession ?? fromLocal;
      if (raw === '1' || raw === '0') {
        setRedactionEnabled(raw === '1');
      }
    } catch {}
  }, []);

  const handleRedactionChange = useCallback((value: boolean) => {
    setRedactionEnabled(value);
    // Persist across refreshes
    try { window.sessionStorage.setItem("assist:redactionEnabled", value ? "1" : "0"); } catch {}
    try { window.localStorage.setItem("assist:redactionEnabled", value ? "1" : "0"); } catch {}
  }, []);

  const handleUploadClick = () => {
    if (!allowKnowledgeUpload || hasActiveUploads) return;
    setShowFileWarningDialog(true);
  };

  const handleFileWarningConfirm = useCallback(() => {
    setShowFileWarningDialog(false);
    // Open file picker after closing the warning dialog
    requestAnimationFrame(() => {
      fileInputRef.current?.click();
    });
  }, []);

  const handleFileWarningClose = useCallback(() => {
    setShowFileWarningDialog(false);
  }, []);

  const handleUpload = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      if (!projectId || !allowKnowledgeUpload) {
        event.target.value = "";
        return;
      }
      const fileList = event.target.files;
      if (!fileList || fileList.length === 0) return;

      const files = Array.from(fileList);

      // Validate all files first
      const validFiles: File[] = [];
      for (const file of files) {
        if (!isAllowedFile(file)) {
          addToast({
            type: "error",
            title: `${file.name} rejected`,
            description: `Unsupported file type. Supported formats: ${ALLOWED_FORMATS_DISPLAY}`,
          });
          continue;
        }

        if (file.size > MAX_FILE_SIZE_BYTES) {
          const pretty = formatBytes(file.size);
          const maxPretty = formatBytes(MAX_FILE_SIZE_BYTES);
          addToast({
            type: "error",
            title: `${file.name} rejected`,
            description: `File is too large (${pretty}). Maximum allowed is ${maxPretty}.`,
          });
          continue;
        }
        validFiles.push(file);
      }

      if (validFiles.length === 0) {
        event.target.value = "";
        return;
      }

      // Add all files to upload manager
      const uploadIds = validFiles.map((file) => uploadStateManager.addUpload(projectId, file));

      // Upload all files in parallel - track results locally to avoid stale closure state
      const uploadResults = await Promise.all(
        uploadIds.map(async (uploadId) => {
          const item = uploadStateManager.getUploads(projectId).find((u) => u.id === uploadId);
          if (!item) return false;

          uploadStateManager.updateUpload(uploadId, { state: "uploading" });

          try {
            const record = await uploadProjectKnowledgeFile(projectId, item.file, { redact: redactionEnabled });
            uploadStateManager.updateUpload(uploadId, {
              state:
                record.processing_status === "pending" || record.processing_status === "processing"
                  ? "processing"
                  : record.processing_status === "failed"
                    ? "error"
                    : "success",
              uploadedFileId: record.id,
              displayName: record.original_filename,
              error: record.processing_status === "failed" ? (record.processing_error || "Processing failed") : undefined,
            });
            return record.processing_status !== "failed";
          } catch (err) {
            const message = err instanceof Error ? err.message : "Upload failed";
            uploadStateManager.updateUpload(uploadId, {
              state: "error",
              error: message,
            });
            addToast({
              type: "error",
              title: `${item.file.name} failed`,
              description: message,
            });
            return false; // Failure
          }
        })
      );

      // Refresh the knowledge list
      await refresh();

      // Show success toast - count from actual results, not stale React state
      const successCount = uploadResults.filter(Boolean).length;
      if (successCount > 0) {
        addToast({
          type: "success",
          title: successCount === 1 ? "File uploaded" : "Files uploaded",
          description: `${successCount} file${successCount === 1 ? "" : "s"} added to knowledge base`,
        });
      }

      event.target.value = "";
    },
    [
      addToast,
      projectId,
      refresh,
      isAllowedFile,
      allowKnowledgeUpload,
      redactionEnabled,
    ],
  );

  const performDelete = useCallback(
    async (file: ProjectKnowledgeFileItem) => {
      if (!projectId) return;

      setDeletingId(file.id);
      try {
        await deleteProjectKnowledgeFile(projectId, file.id);
        await refresh();
        addToast({ type: "success", title: "File removed" });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to delete file";
        addToast({ type: "error", title: "Couldn't delete", description: message });
      } finally {
        setDeletingId(null);
      }
    },
    [addToast, projectId, refresh],
  );

  const triggerDownloadSimple = useCallback((url: string) => {
    if (!url) return;
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  }, []);

  const handleDownloadSimple = useCallback(
    async (file: ProjectKnowledgeFileItem) => {
      setDownloadSimpleingId(file.id);
      try {
        const result = await getFileDownloadUrl({ fileId: file.id });
        if (!result?.download_url) {
          throw new Error("DownloadSimple link unavailable");
        }
        triggerDownloadSimple(result.download_url);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to get download link";
        addToast({ type: "error", title: "Couldn't download", description: message });
      } finally {
        setDownloadSimpleingId(null);
      }
    },
    [addToast, triggerDownloadSimple],
  );

  const performDeleteAll = useCallback(async () => {
    if (!projectId) return;
    setDeletingAll(true);
    try {
      const result = await deleteAllProjectKnowledgeFiles(projectId);
      await refresh();
      addToast({ type: "success", title: `${result.deleted} file${result.deleted === 1 ? "" : "s"} removed` });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to delete files";
      addToast({ type: "error", title: "Couldn't delete all", description: message });
    } finally {
      setDeletingAll(false);
    }
  }, [addToast, projectId, refresh]);

  const handleDownloadSimpleAll = useCallback(async () => {
    if (!projectId || totalFiles === 0) return;

    setDownloadSimpleingAll(true);
    try {
      let archiveJob = await createProjectKnowledgeArchiveJob(projectId);
      for (let attempt = 0; attempt < 90; attempt += 1) {
        if (archiveJob.status === "completed") {
          if (!archiveJob.download_url) {
            throw new Error("Archive download link unavailable");
          }
          triggerDownloadSimple(archiveJob.download_url);
          const successCount = archiveJob.included_files > 0 ? archiveJob.included_files : totalFiles;
          addToast({
            type: "success",
            title: `DownloadSimpleing ${successCount} file${successCount === 1 ? "" : "s"}`,
          });

          if (archiveJob.skipped_files > 0) {
            addToast({
              type: "error",
              title: `${archiveJob.skipped_files} file${archiveJob.skipped_files === 1 ? "" : "s"} skipped`,
              description: "Some files were unavailable and were not included in the archive.",
            });
          }
          return;
        }

        if (archiveJob.status === "failed") {
          throw new Error(archiveJob.error || "Archive generation failed");
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
        archiveJob = await getProjectKnowledgeArchiveJob(projectId, archiveJob.job_id);
      }
      throw new Error("Archive is still processing. Retry in a moment.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to download files";
      addToast({ type: "error", title: "Couldn't download all", description: message });
    } finally {
      setDownloadSimpleingAll(false);
    }
  }, [addToast, projectId, totalFiles, triggerDownloadSimple]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to refresh";
      addToast({ type: "error", title: "Couldn't refresh", description: message });
    } finally {
      setRefreshing(false);
    }
  }, [addToast, refresh]);

  const summaryStats = useMemo(
    () => ({ totalFiles, totalSize, fileTypes }),
    [totalFiles, totalSize, fileTypes],
  );

  const hasFiles = knowledge.length > 0;
  const isEmpty = totalFiles === 0 && visibleUploads.length === 0 && !hasProcessingFiles && !isLoading;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={projectName ? `Manage files for "${projectName}"` : "Manage project files"}
      className="sm:max-w-2xl"
    >
      {/* Hidden file input - always present */}
      <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleUpload} accept={FILE_ACCEPT_STRING} />

      {/* Empty state */}
      {isEmpty ? (
        <div className="flex flex-col items-center justify-center py-12">
          {showUploadControls ? (
            <Button
              type="button"
              variant="outline"
              onClick={handleUploadClick}
              disabled={uploadButtonDisabled}
              className={cn(
                "h-auto rounded-xl border-dashed px-4 py-2.5",
                "type-size-14 text-muted-foreground hover:text-foreground hover:border-border"
              )}
            >
              <CloudArrowUp className="size-4" aria-hidden />
              <span>Add files</span>
            </Button>
          ) : (
            <FileText className="size-8 text-muted-foreground/60" aria-hidden />
          )}
          <p className="mt-3 type-size-12 text-muted-foreground text-center max-w-xs">
            {showUploadControls ? emptyStateHelpText : "No files in this project."}
          </p>
        </div>
      ) : null}

      {/* Full UI when there are files or activity */}
      {!isEmpty ? (
        <div className="space-y-5">
          {showUploadControls ? (
            <section className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3 sm:px-5 sm:py-4 transition-colors">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <p className="type-size-12 font-medium uppercase tracking-[0.08em] text-muted-foreground">Knowledge base</p>
                  <h4 className="type-size-14 font-semibold text-foreground">
                    {summaryStats.totalFiles} file{summaryStats.totalFiles === 1 ? "" : "s"}
                    {summaryStats.totalSize ? ` • ${formatBytes(summaryStats.totalSize)}` : ""}
                  </h4>
                  {summaryStats.totalFiles > 0 ? (
                    <p className="type-size-12 text-muted-foreground/80">
                      {Object.keys(summaryStats.fileTypes)
                        .slice(0, 3)
                        .map((type) => `${type} (${summaryStats.fileTypes[type]})`)
                        .join(" • ")}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-col items-end gap-2 sm:flex-row sm:items-center">
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="h-10 gap-2 rounded-lg border-border/60 bg-background"
                      onClick={handleUploadClick}
                      disabled={uploadButtonDisabled}
                    >
                      {hasActiveUploads ? <SpinnerGap className="size-4 animate-spin" /> : <CloudArrowUp className="size-4" />}
                      {hasPendingUploads ? "Uploading…" : hasProcessingFiles ? "Processing…" : "Add files"}
                    </Button>
                  </div>
                </div>
              </div>
            </section>
          ) : null}

          {/* Active uploads section */}
          {visibleUploads.length > 0 ? (
          <section className="space-y-3">
            {(() => {
              const activeCount = visibleUploads.filter((u) => u.state === "uploading" || u.state === "pending" || u.state === "processing").length;
              const successCount = visibleUploads.filter((u) => u.state === "success").length;
              const errorCount = visibleUploads.filter((u) => u.state === "error").length;
              const totalCount = visibleUploads.length;
              const showCompact = totalCount > 3 && !uploadsExpanded;

              return (
                <>
                  <div className="flex items-center justify-between gap-2">
                    <h5 className="type-size-14 font-semibold text-foreground">
                      Uploads
                      {activeCount > 0 ? ` (${activeCount} active)` : ""}
                    </h5>
                    <div className="flex items-center gap-1">
                      {totalCount > 3 ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setUploadsExpanded(!uploadsExpanded)}
                          className="type-size-12"
                        >
                          {uploadsExpanded ? "Collapse" : "Show all"}
                        </Button>
                      ) : null}
                      {(successCount > 0 || errorCount > 0) ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => projectId && uploadStateManager.clearCompleted(projectId)}
                          className="type-size-12"
                        >
                          Clear
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  {/* Compact summary bar for many uploads */}
                  {showCompact ? (
                    <div className="rounded-xl border border-border/50 bg-muted/20 p-3">
                      <div className="flex items-center gap-3">
                        {activeCount > 0 ? (
                          <SpinnerGap className="size-4 text-amber-600 dark:text-amber-400 animate-spin shrink-0" aria-hidden />
                        ) : successCount > 0 && errorCount === 0 ? (
                          <CheckCircle className="size-4 text-emerald-600 dark:text-emerald-400 shrink-0" aria-hidden />
                        ) : (
                          <FileText className="size-4 text-muted-foreground shrink-0" aria-hidden />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="type-size-14 font-medium text-foreground">
                            {totalCount} file{totalCount === 1 ? "" : "s"}
                          </p>
                          <p className="type-size-10 text-muted-foreground/90">
                            {[
                              activeCount > 0 && `${activeCount} uploading`,
                              successCount > 0 && `${successCount} uploaded`,
                              errorCount > 0 && `${errorCount} failed`,
                            ].filter(Boolean).join(" · ")}
                          </p>
                        </div>
                        {/* Progress bar */}
                        {totalCount > 0 ? (
                          <div className="w-24 h-1.5 rounded-full bg-muted overflow-hidden shrink-0">
                            <div
                              className={cn(
                                "h-full rounded-full transition-all duration-300",
                                errorCount > 0 ? "bg-destructive" : "bg-emerald-500"
                              )}
                              style={{ width: `${Math.round(((successCount + errorCount) / totalCount) * 100)}%` }}
                            />
                          </div>
                        ) : null}
                      </div>
                      {/* Show only error items inline */}
                      {errorCount > 0 ? (
                        <ul className="mt-2 space-y-1">
                          {visibleUploads.filter((u) => u.state === "error").map((upload) => (
                            <li key={upload.id} className="flex items-center gap-2 rounded-lg bg-destructive/5 px-2 py-1">
                              <XCircle className="size-3 text-destructive shrink-0" aria-hidden />
                              <p className="truncate type-size-12 text-destructive">{upload.displayName || upload.file.name}</p>
                              <span className="type-size-10 text-destructive/70 shrink-0">{upload.error}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : (
                    /* Expanded individual items list */
                    <ul className="space-y-1">
                      {visibleUploads.map((upload) => {
                        const isUploading = upload.state === "uploading";
                        const isPending = upload.state === "pending";
                        const isProcessing = upload.state === "processing";
                        const isSuccess = upload.state === "success";
                        const isError = upload.state === "error";
                        const uploadName = upload.displayName || upload.file.name;

                        return (
                          <li
                            key={upload.id}
                            className={cn(
                              "rounded-xl border p-2 shadow-sm transition-colors",
                              isSuccess && "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200/50 dark:border-emerald-800/30",
                              isError && "bg-destructive/5 border-destructive/30",
                              isProcessing && "bg-amber-50/50 dark:bg-amber-950/20 border-amber-200/50 dark:border-amber-800/30",
                              (isUploading || isPending) && "bg-muted/20 border-border/50"
                            )}
                          >
                            <div className="flex items-start gap-2">
                              <span
                                className={cn(
                                  "flex size-7 shrink-0 items-center justify-center rounded-full border",
                                  isSuccess && "bg-emerald-100 dark:bg-emerald-900/40 border-emerald-300 dark:border-emerald-700",
                                  isError && "bg-destructive/10 border-destructive/40",
                                  isProcessing && "bg-amber-100 dark:bg-amber-900/40 border-amber-300 dark:border-amber-700",
                                  (isUploading || isPending) && "bg-muted/30 border-border/40"
                                )}
                              >
                                {isUploading && <SpinnerGap className="size-4 text-muted-foreground animate-spin" aria-hidden />}
                                {isPending && <FileText className="size-4 text-muted-foreground" aria-hidden />}
                                {isProcessing && <SpinnerGap className="size-4 text-amber-600 dark:text-amber-400 animate-spin" aria-hidden />}
                                {isSuccess && <CheckCircle className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden />}
                                {isError && <XCircle className="size-4 text-destructive" aria-hidden />}
                              </span>
                              <div className="flex-1 min-w-0">
                                <p className="truncate type-size-14 font-medium text-foreground" title={uploadName}>
                                  {uploadName}
                                </p>
                                <p className="mt-0.25 type-size-10 leading-snug text-muted-foreground/90">
                                  {formatBytes(upload.file.size)}
                                  {isUploading && " • Uploading…"}
                                  {isPending && " • Waiting…"}
                                  {isProcessing && " • Analyzing content…"}
                                  {isSuccess && " • Uploaded"}
                                  {isError && upload.error && ` • ${upload.error}`}
                                </p>
                              </div>
                              {(isSuccess || isError) && (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  onClick={() => uploadStateManager.removeUpload(upload.id)}
                                  aria-label="Remove from list"
                                >
                                  <X className="size-4" />
                                </Button>
                              )}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </>
              );
            })()}
          </section>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 type-size-14 text-destructive">
            <div className="flex items-start gap-2">
              <Warning className="mt-0.5 size-4" aria-hidden />
              <div>
                <p className="font-medium">{error.message}</p>
                <Button
                  type="button"
                  variant="link"
                  onClick={handleRefresh}
                  className="mt-2 h-auto p-0 type-size-12 font-medium text-destructive underline-offset-2 hover:underline"
                >
                  Try again
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h5 className="type-size-14 font-semibold text-foreground">Files</h5>
            <div className="flex items-center gap-1">
              {isLoading ? <span className="type-size-12 text-muted-foreground">Loading…</span> : null}
              {summaryStats.totalFiles > 1 ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 type-size-12 gap-1 px-2"
                    onClick={handleDownloadSimpleAll}
                    aria-label="DownloadSimple all files"
                    disabled={downloadingAll || hasProcessingFiles}
                    title={hasProcessingFiles ? "Wait for file processing to finish before downloading all files" : undefined}
                  >
                    {downloadingAll ? (
                      <SpinnerGap className="size-3.5 animate-spin" aria-hidden />
                    ) : (
                      <DownloadSimple className="size-3.5" aria-hidden />
                    )}
                    All
                  </Button>
                  {canManageKnowledge ? (
                    <ConfirmButton
                      onConfirm={performDeleteAll}
                      confirmLabel="Confirm delete"
                      variant="ghost"
                      size="sm"
                      className="h-7 type-size-12 gap-1 px-2 text-destructive hover:text-destructive"
                      disabled={deletingAll}
                      aria-label="Delete all files"
                      confirmVariant="destructive"
                      confirmSize="sm"
                    >
                      {deletingAll ? <SpinnerGap className="size-3.5 animate-spin" aria-hidden /> : <Trash className="size-3.5" aria-hidden />}
                      Delete all
                    </ConfirmButton>
                  ) : null}
                </>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={handleRefresh}
                aria-label="Refresh files"
                disabled={refreshing}
              >
                {refreshing ? <SpinnerGap className="size-3.5 animate-spin" aria-hidden /> : <ArrowsClockwise className="size-3.5" aria-hidden />}
              </Button>
            </div>
          </div>

          {isLoading && !hasFiles ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, idx) => (
                <div key={`knowledge-skeleton-${idx}`} className="flex items-center gap-3 rounded-lg border border-border/50 bg-muted/10 p-3">
                  <Skeleton className="size-9 rounded-full" />
                  <div className="flex-1 space-y-1">
                    <Skeleton className="h-3 w-1/2" />
                    <Skeleton className="h-3 w-1/3" />
                  </div>
                  <Skeleton className="size-8 rounded-full" />
                </div>
              ))}
            </div>
          ) : null}

          {hasFiles ? (
            <>
              <ul className="space-y-1">
                {knowledge.map((file) => {
                const sizeLabel = formatBytes(file.file_size);
                const uploader = file.uploaded_by?.name || file.uploaded_by?.email || "Unknown";
                const isDeleting = deletingId === file.id;
                const isDownloadSimpleing = downloadingId === file.id;
                const canManage = canManageFile(file);

                const processingStatus = file.processing_status ?? "completed";
                const isFileProcessing = processingStatus === "pending" || processingStatus === "processing";
                const isFileFailed = processingStatus === "failed";

                return (
                  <li
                    key={file.id}
                    className={cn(
                      "rounded-xl border p-2 shadow-sm transition-colors",
                      isFileProcessing && "bg-amber-50/50 dark:bg-amber-950/20 border-amber-200/50 dark:border-amber-800/30",
                      isFileFailed && "bg-destructive/5 border-destructive/30",
                      !isFileProcessing && !isFileFailed && (canManage ? "bg-background/80 border-border/50" : "bg-muted/20 border-border/30 opacity-95")
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <span
                        className={cn(
                          "flex size-7 shrink-0 items-center justify-center rounded-full border",
                          isFileProcessing && "bg-amber-100 dark:bg-amber-900/40 border-amber-300 dark:border-amber-700",
                          isFileFailed && "bg-destructive/10 border-destructive/40",
                          !isFileProcessing && !isFileFailed && (canManage ? "bg-muted/30 border-border/40" : "bg-muted/20 border-border/30")
                        )}
                      >
                        {isFileProcessing ? (
                          <SpinnerGap className="size-4 text-amber-600 dark:text-amber-400 animate-spin" aria-hidden />
                        ) : isFileFailed ? (
                          <XCircle className="size-4 text-destructive" aria-hidden />
                        ) : (
                          <FileText className="size-4 text-muted-foreground" aria-hidden />
                        )}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="truncate type-size-14 font-medium text-foreground" title={file.original_filename}>
                          {file.original_filename}
                        </p>
                        <p className="mt-0.25 type-size-10 leading-snug text-muted-foreground/90">
                          {sizeLabel ? `${sizeLabel} • ` : ""}
                          {file.file_type}
                          {isFileProcessing && " • Analyzing content…"}
                          {isFileFailed && " • Processing failed"}
                          {!isFileProcessing && !isFileFailed && uploader ? ` • ${uploader}` : ""}
                        </p>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => handleDownloadSimple(file)}
                          disabled={isDownloadSimpleing || isFileProcessing}
                          aria-label={`DownloadSimple ${file.original_filename}`}
                          title={isFileProcessing ? "File is still being processed" : undefined}
                        >
                          {isDownloadSimpleing ? <SpinnerGap className="size-4 animate-spin" /> : <DownloadSimple className="size-4" />}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          aria-label={
                            canManage
                              ? `Delete ${file.original_filename}`
                              : `You cannot delete ${file.original_filename}`
                          }
                          disabled={!canManage || isDeleting}
                          onClick={() => performDelete(file)}
                        >
                          {isDeleting ? <SpinnerGap className="size-4 animate-spin" /> : <Trash className="size-4" />}
                        </Button>
                      </div>
                    </div>
                  </li>
                );
                })}
              </ul>
              {hasMoreFiles ? (
                <div className="flex justify-center pt-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      void loadMoreFiles();
                    }}
                    disabled={isFetchingMore}
                  >
                    {isFetchingMore ? <SpinnerGap className="size-4 animate-spin" /> : null}
                    {isFetchingMore ? "Loading…" : "Load more"}
                  </Button>
                </div>
              ) : null}
            </>
          ) : null}
        </section>
        </div>
      ) : null}

      {/* File Upload Warning Dialog */}
      <FileUploadWarningDialog
        open={showFileWarningDialog}
        onClose={handleFileWarningClose}
        onConfirm={handleFileWarningConfirm}
        showRedactionToggle={true}
        redactionEnabled={redactionEnabled}
        onRedactionChange={handleRedactionChange}
        redactionDisabled={hasActiveUploads}
        confirmText="Select files"
      />
    </Modal>
  );
}
