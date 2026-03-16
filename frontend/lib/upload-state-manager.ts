/**
 * Global upload state manager for project knowledge files.
 * Persists upload state even when dialog is closed.
 * 
 * Supports both immediate uploads and background processing tracking.
 */

type UploadState = "pending" | "uploading" | "success" | "error" | "processing";

export type FileUploadItem = {
  id: string; // Unique ID for tracking
  file: File;
  displayName?: string; // Backend-provided safe filename after upload
  projectId: string;
  state: UploadState;
  error?: string;
  uploadedFileId?: string; // Backend file ID after success
  progress?: number; // Future: for progress tracking
};

type UploadListener = (items: FileUploadItem[]) => void;

class UploadStateManager {
  private uploads = new Map<string, FileUploadItem>();
  private listeners = new Set<UploadListener>();

  subscribe(listener: UploadListener): () => void {
    this.listeners.add(listener);
    // Immediately notify of current state
    listener(this.getUploads());
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify() {
    const items = this.getUploads();
    this.listeners.forEach((listener) => listener(items));
  }

  addUpload(projectId: string, file: File): string {
    const id = `${projectId}-${file.name}-${Date.now()}-${Math.random()}`;
    this.uploads.set(id, {
      id,
      file,
      projectId,
      state: "pending",
    });
    this.notify();
    return id;
  }

  updateUpload(id: string, updates: Partial<Omit<FileUploadItem, "id" | "file" | "projectId">>) {
    const existing = this.uploads.get(id);
    if (!existing) return;

    this.uploads.set(id, {
      ...existing,
      ...updates,
    });
    this.notify();
  }

  removeUpload(id: string) {
    this.uploads.delete(id);
    this.notify();
  }

  clearCompleted(projectId?: string) {
    const toDelete: string[] = [];
    this.uploads.forEach((item, id) => {
      if (item.state === "success" || item.state === "error") {
        if (!projectId || item.projectId === projectId) {
          toDelete.push(id);
        }
      }
    });
    toDelete.forEach((id) => this.uploads.delete(id));
    this.notify();
  }

  getUploads(projectId?: string): FileUploadItem[] {
    const items = Array.from(this.uploads.values());
    if (projectId) {
      return items.filter((item) => item.projectId === projectId);
    }
    return items;
  }

  getActiveCount(projectId?: string): number {
    return this.getUploads(projectId).filter(
      (item) => item.state === "pending" || item.state === "uploading" || item.state === "processing"
    ).length;
  }

  hasActiveUploads(projectId?: string): boolean {
    return this.getActiveCount(projectId) > 0;
  }

}

export const uploadStateManager = new UploadStateManager();
