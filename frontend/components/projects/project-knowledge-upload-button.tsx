
import { useCallback, useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ChartBar as FileChartColumn, SpinnerGap, Plus } from "@phosphor-icons/react";
import { ProjectKnowledgeDialog } from "@/components/projects/project-knowledge-dialog";
import { useProjectKnowledge } from "@/hooks/use-project-knowledge";
import { cn } from "@/lib/utils";
import { uploadStateManager } from "@/lib/upload-state-manager";

interface ProjectKnowledgeUploadButtonProps {
  projectId?: string | null;
  projectName?: string | null;
  canManageKnowledge?: boolean;
  canUploadKnowledge?: boolean;
  isPublicProject?: boolean;
  disabled?: boolean;
}

export const ProjectKnowledgeUploadButton: React.FC<ProjectKnowledgeUploadButtonProps> = ({
  projectId,
  projectName,
  canManageKnowledge,
  canUploadKnowledge,
  isPublicProject,
  disabled,
}) => {
  const [open, setOpen] = useState(false);
  const [activeUploadCount, setActiveUploadCount] = useState(0);
  const hasProject = Boolean(projectId);
  const effectiveProjectId = hasProject ? projectId ?? null : null;
  const { totalFiles, isLoading, hasProcessingFiles, refresh } = useProjectKnowledge(effectiveProjectId);
  const fileCount = typeof totalFiles === "number" && totalFiles > 0 ? totalFiles : 0;
  const processingFilesCount = hasProcessingFiles ? 1 : 0;

  // Subscribe to upload state manager to show badge when uploads are active
  // Includes "processing" state for background file parsing
  useEffect(() => {
    const unsubscribe = uploadStateManager.subscribe((uploads) => {
      if (!projectId) return;
      const count = uploads.filter(
        (u) => u.projectId === projectId && (u.state === "uploading" || u.state === "pending" || u.state === "processing")
      ).length;
      setActiveUploadCount(count);
    });
    return unsubscribe;
  }, [projectId]);

  // No interval polling: when uploads settle, trigger a single refresh to
  // pick up backend processing state transitions.
  useEffect(() => {
    if (!projectId) return;
    if (activeUploadCount === 0 && processingFilesCount > 0) {
      void refresh();
    }
  }, [activeUploadCount, processingFilesCount, projectId, refresh]);

  // Combine both sources of active processing
  const totalActiveCount = Math.max(activeUploadCount, processingFilesCount);
  const descriptiveCount = isLoading
    ? "loading"
    : fileCount === 0
      ? "0 files"
      : fileCount === 1
        ? "1 file"
        : `${fileCount} files`;
  const labelDetail = !hasProject ? "Project unavailable" : `Manage project files (${descriptiveCount})`;

  const handleOpen = useCallback(() => {
    if (!hasProject || disabled) return;
    setOpen(true);
  }, [disabled, hasProject]);

  const handleClose = useCallback(() => setOpen(false), []);

  const isEmpty = !isLoading && fileCount === 0;

  return (
    <>
      <div className="relative shrink-0">
        {isEmpty ? (
          /* Empty state: show "Add files" button */
          <Button
            type="button"
            variant="outline"
            size="lg"
            className={cn(
              "group h-10 sm:h-12 rounded-full border px-3 sm:px-4 type-size-14 font-medium shadow-sm transition-all duration-200",
              "border-dashed border-border/60 bg-transparent text-muted-foreground hover:text-foreground hover:border-border hover:bg-muted/30",
            )}
            onClick={handleOpen}
            disabled={!hasProject || disabled}
            aria-label="Add files to project"
          >
            <Plus className="size-4 text-current shrink-0" weight="bold" aria-hidden />
            <span className="type-size-14">Add files</span>
          </Button>
        ) : (
          /* Has files: show file count badge */
          <Button
            type="button"
            variant="outline"
            size="lg"
            className={cn(
              "group h-10 sm:h-12 rounded-lg border px-2.5 sm:px-4 type-size-14 font-medium shadow-sm transition-all duration-200",
              "border-transparent bg-[color:var(--primary-surface)] text-primary hover:bg-[color:var(--primary-surface-strong)] hover:text-primary hover:shadow-md",
              "dark:bg-[color:var(--primary-surface)] dark:text-[color:var(--primary-surface-foreground)] dark:hover:bg-[color:var(--primary-surface-strong)]",
            )}
            onClick={handleOpen}
            disabled={!hasProject || disabled}
            aria-label={labelDetail}
          >
            <FileChartColumn className="size-4 sm:size-5 text-current shrink-0" aria-hidden />
            <span className="inline-flex size-6 sm:size-8 items-center justify-center rounded-[0.5rem] sm:rounded-[0.75rem] bg-[color:var(--primary-surface-strong)] type-size-14 font-semibold leading-none text-primary shadow-xs transition-colors group-hover:text-primary dark:bg-[color:var(--primary-surface-strong)] dark:text-[color:var(--primary-surface-foreground)]">
              {isLoading || totalActiveCount > 0 ? <SpinnerGap className="size-3 sm:size-4 animate-spin" aria-hidden /> : fileCount}
            </span>
            <span className="sr-only">{labelDetail}</span>
          </Button>
        )}
      </div>
      <ProjectKnowledgeDialog
        open={open}
        onClose={handleClose}
        projectId={projectId ?? null}
        projectName={projectName}
        canManageKnowledge={canManageKnowledge}
        canUploadKnowledge={canUploadKnowledge}
        isPublicProject={isPublicProject}
      />
    </>
  );
};
