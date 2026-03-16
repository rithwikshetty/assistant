import { useCallback, useEffect, useRef, useState, type ChangeEvent, type MutableRefObject } from "react";
import { useToast } from "@/components/ui/toast";
import { useFileDrop } from "@/contexts/file-drop-context";
import {
  uploadStagedFile,
  cancelStagedUpload,
  deleteStagedFile,
  getStagedFile,
  type StagedFileUploadResponse,
} from "@/lib/api/staged-files";
import {
  ALLOWED_FORMATS_DISPLAY,
  MAX_FILE_SIZE_BYTES,
  isAllowedFile,
} from "@/lib/file-types";
import { formatBytes } from "@/lib/attachments";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";
import type { Attachment } from "@/components/chat/chat-input.shared";

type UseChatInputAttachmentsOptions = {
  redactionRef: MutableRefObject<boolean>;
};

type UseChatInputAttachmentsResult = {
  attachments: Attachment[];
  hasUploadingAttachment: boolean;
  handleFilesSelected: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  removeAttachment: (id: string) => Promise<void>;
  clearAttachments: () => void;
};

const MAX_FILES = 10;
const UPLOAD_CONCURRENCY = 5;

function generateUploadId(): string {
  try {
    return (
      crypto?.randomUUID?.() ??
      `upload_${Date.now()}_${Math.random().toString(16).slice(2)}`
    );
  } catch {
    return `upload_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }
}

function createPendingAttachment(file: File): Attachment {
  return {
    id: `temp_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    uploadId: generateUploadId(),
    file,
    name: file.name,
    size: file.size,
    status: "uploading",
  };
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException) {
    return error.name === "AbortError";
  }
  return error instanceof Error && error.name === "AbortError";
}

export function useChatInputAttachments({
  redactionRef,
}: UseChatInputAttachmentsOptions): UseChatInputAttachmentsResult {
  const backendBase = getBackendBaseUrl();
  const { addToast } = useToast();
  const { registerFileHandler, unregisterFileHandler } = useFileDrop();
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const uploadControllersRef = useRef<Map<string, AbortController>>(new Map());
  const statusControllersRef = useRef<Map<string, AbortController>>(new Map());
  const cancelledAttachmentIdsRef = useRef<Set<string>>(new Set());

  const uploadFile = useCallback(
    async (
      file: File,
      options?: { uploadId?: string; signal?: AbortSignal }
    ): Promise<StagedFileUploadResponse | null> => {
      if (!isAllowedFile(file)) {
        addToast({
          type: "error",
          title: "Unsupported file type",
          description: `Supported formats: ${ALLOWED_FORMATS_DISPLAY}`,
        });
        return null;
      }

      if (file.size > MAX_FILE_SIZE_BYTES) {
        addToast({
          type: "error",
          title: "File too large",
          description: `Maximum size is ${formatBytes(MAX_FILE_SIZE_BYTES)}`,
        });
        return null;
      }

      try {
        return await uploadStagedFile({
          baseUrl: backendBase,
          file,
          uploadId: options?.uploadId,
          redact: redactionRef.current,
          signal: options?.signal,
        });
      } catch (error) {
        if (isAbortError(error)) {
          return null;
        }

        if (error instanceof Error && /upload cancelled/i.test(error.message)) {
          return null;
        }

        addToast({
          type: "error",
          title: "Couldn't upload file",
          description: error instanceof Error ? error.message : "Upload failed",
        });
        return null;
      }
    },
    [addToast, backendBase, redactionRef]
  );

  const pollStagedFileStatus = useCallback(
    async (attachmentId: string, stagedId: string) => {
      const controller = new AbortController();
      statusControllersRef.current.set(attachmentId, controller);

      try {
        for (let attempt = 0; attempt < 120; attempt += 1) {
          const staged = await getStagedFile({
            baseUrl: backendBase,
            stagedId,
            signal: controller.signal,
          });

          if (cancelledAttachmentIdsRef.current.has(attachmentId)) {
            return;
          }

          if (staged.processing_status === "completed") {
            setAttachments((prev) =>
              prev.map((existing) =>
                existing.id === attachmentId
                  ? {
                      ...existing,
                      status: "ready",
                      backendId: staged.id,
                      meta: staged,
                      errorMessage: undefined,
                    }
                  : existing
              )
            );
            return;
          }

          if (staged.processing_status === "failed") {
            setAttachments((prev) =>
              prev.map((existing) =>
                existing.id === attachmentId
                  ? {
                      ...existing,
                      status: "error",
                      backendId: staged.id,
                      meta: staged,
                      errorMessage: staged.processing_error || "Processing failed",
                    }
                  : existing
              )
            );
            return;
          }

          setAttachments((prev) =>
            prev.map((existing) =>
              existing.id === attachmentId
                ? {
                    ...existing,
                    status: "processing",
                    backendId: staged.id,
                    meta: staged,
                  }
                : existing
            )
          );
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }

        setAttachments((prev) =>
          prev.map((existing) =>
            existing.id === attachmentId
              ? {
                  ...existing,
                  status: "error",
                  errorMessage: "Attachment processing timed out",
                }
              : existing
          )
        );
      } catch (error) {
        if (!isAbortError(error)) {
          setAttachments((prev) =>
            prev.map((existing) =>
              existing.id === attachmentId
                ? {
                    ...existing,
                    status: "error",
                    errorMessage: error instanceof Error ? error.message : "Attachment processing failed",
                  }
                : existing
            )
          );
        }
      } finally {
        statusControllersRef.current.delete(attachmentId);
      }
    },
    [backendBase]
  );

  const processFiles = useCallback(
    async (files: FileList) => {
      if (files.length === 0) {
        return;
      }

      const currentCount = attachments.length;
      if (currentCount + files.length > MAX_FILES) {
        addToast({
          type: "error",
          title: "Too many files",
          description: `Maximum ${MAX_FILES} files allowed.`,
        });
        return;
      }

      const newAttachments = Array.from(files).map(createPendingAttachment);
      setAttachments((prev) => [...prev, ...newAttachments]);

      const queue = [...newAttachments];
      const workerCount = Math.min(UPLOAD_CONCURRENCY, queue.length);
      const workers = Array.from({ length: workerCount }, async () => {
        while (queue.length > 0) {
          const attachment = queue.shift();
          if (!attachment) {
            return;
          }

          if (cancelledAttachmentIdsRef.current.has(attachment.id)) {
            cancelledAttachmentIdsRef.current.delete(attachment.id);
            continue;
          }

          const controller = new AbortController();
          uploadControllersRef.current.set(attachment.id, controller);

          const result = await uploadFile(attachment.file, {
            uploadId: attachment.uploadId,
            signal: controller.signal,
          });

          uploadControllersRef.current.delete(attachment.id);

          if (cancelledAttachmentIdsRef.current.has(attachment.id)) {
            cancelledAttachmentIdsRef.current.delete(attachment.id);
            if (result?.id) {
              try {
                await deleteStagedFile({
                  baseUrl: backendBase,
                  stagedId: result.id,
                });
              } catch {
                // Ignore cleanup failures after cancellation.
              }
            }
            continue;
          }

          setAttachments((prev) =>
            prev.map((existing) =>
              existing.id === attachment.id
                ? result
                  ? result.processing_status === "completed"
                    ? {
                        ...existing,
                        status: "ready",
                        backendId: result.id,
                        meta: result,
                        errorMessage: undefined,
                      }
                    : result.processing_status === "failed"
                      ? {
                          ...existing,
                          status: "error",
                          backendId: result.id,
                          meta: result,
                          errorMessage: result.processing_error || "Attachment processing failed",
                        }
                      : {
                          ...existing,
                          status: "processing",
                          backendId: result.id,
                          meta: result,
                          errorMessage: undefined,
                        }
                  : {
                      ...existing,
                      status: "error",
                      errorMessage: "Upload failed",
                    }
                : existing
            )
          );

          if (
            result?.id &&
            !cancelledAttachmentIdsRef.current.has(attachment.id) &&
            result.processing_status !== "completed" &&
            result.processing_status !== "failed"
          ) {
            void pollStagedFileStatus(attachment.id, result.id);
          }
        }
      });

      await Promise.all(workers);
    },
    [addToast, attachments.length, backendBase, pollStagedFileStatus, uploadFile]
  );

  const handleFilesSelected = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const { files } = event.target;
      if (files) {
        await processFiles(files);
      }
      event.target.value = "";
    },
    [processFiles]
  );

  useEffect(() => {
    registerFileHandler(processFiles);
    return () => {
      unregisterFileHandler();
    };
  }, [processFiles, registerFileHandler, unregisterFileHandler]);

  useEffect(() => {
    const uploadControllers = uploadControllersRef.current;
    const statusControllers = statusControllersRef.current;
    const cancelledAttachmentIds = cancelledAttachmentIdsRef.current;

    return () => {
      uploadControllers.forEach((controller) => controller.abort());
      uploadControllers.clear();
      statusControllers.forEach((controller) => controller.abort());
      statusControllers.clear();
      cancelledAttachmentIds.clear();
    };
  }, []);

  const removeAttachment = useCallback(
    async (id: string) => {
      const attachment = attachments.find((item) => item.id === id);
      if (!attachment) {
        return;
      }

      if (attachment.status === "uploading") {
        cancelledAttachmentIdsRef.current.add(id);
        uploadControllersRef.current.get(id)?.abort();
        uploadControllersRef.current.delete(id);
        setAttachments((prev) => prev.filter((item) => item.id !== id));

        try {
          await cancelStagedUpload({
            baseUrl: backendBase,
            uploadId: attachment.uploadId,
          });
        } catch {
          // Ignore cancellation errors; local removal still proceeds.
        }
        return;
      }

      statusControllersRef.current.get(id)?.abort();
      statusControllersRef.current.delete(id);

      if (attachment.backendId) {
        try {
          await deleteStagedFile({
            baseUrl: backendBase,
            stagedId: attachment.backendId,
          });
        } catch {
          // Ignore delete errors.
        }
      }

      cancelledAttachmentIdsRef.current.delete(id);
      setAttachments((prev) => prev.filter((item) => item.id !== id));
    },
    [attachments, backendBase]
  );

  const clearAttachments = useCallback(() => {
    uploadControllersRef.current.forEach((controller) => controller.abort());
    uploadControllersRef.current.clear();
    statusControllersRef.current.forEach((controller) => controller.abort());
    statusControllersRef.current.clear();
    setAttachments([]);
  }, []);

  return {
    attachments,
    hasUploadingAttachment: attachments.some(
      (attachment) => attachment.status === "uploading" || attachment.status === "processing"
    ),
    handleFilesSelected,
    removeAttachment,
    clearAttachments,
  };
}
