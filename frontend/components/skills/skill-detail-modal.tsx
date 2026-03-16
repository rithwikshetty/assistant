import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DownloadSimple, FolderSimple, SpinnerGap } from "@phosphor-icons/react";

import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { markdownComponents } from "@/components/markdown/markdown-components";
import {
  downloadSkillFile,
  getSkillDetail,
  type SkillManifestFile,
  type SkillManifestItem,
} from "@/lib/api/skills";
import { cn } from "@/lib/utils";
import { formatBytes, groupFilesByFolder } from "./skill-utils";

interface SkillDetailModalProps {
  skill: SkillManifestItem | null;
  onClose: () => void;
}

export function SkillDetailModal({ skill, onClose }: SkillDetailModalProps) {
  const { addToast } = useToast();
  const [downloadingPaths, setDownloadingPaths] = React.useState<Set<string>>(new Set());
  const skillFiles = skill?.files ?? [];

  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["skills", "detail", skill?.id || ""],
    queryFn: () => getSkillDetail(skill?.id || ""),
    enabled: Boolean(skill?.id),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const triggerBlobDownload = React.useCallback((blob: Blob, filename: string) => {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename || "skill-file";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }, []);

  const handleDownloadFile = React.useCallback(
    async (skillId: string, file: SkillManifestFile) => {
      const downloadKey = `${skillId}:${file.path}`;
      setDownloadingPaths((prev) => {
        const next = new Set(prev);
        next.add(downloadKey);
        return next;
      });

      try {
        const { blob, filename } = await downloadSkillFile({
          downloadPath: file.download_path,
          fallbackFilename: file.name,
        });
        triggerBlobDownload(blob, filename || file.name);
      } catch (err) {
        const description = err instanceof Error ? err.message : "Please try again.";
        addToast({ type: "error", title: "Couldn't download file", description });
      } finally {
        setDownloadingPaths((prev) => {
          const next = new Set(prev);
          next.delete(downloadKey);
          return next;
        });
      }
    },
    [addToast, triggerBlobDownload],
  );

  return (
    <Modal
      open={skill !== null}
      onClose={onClose}
      title={skill?.title || ""}
      size="4xl"
      className="sm:h-[75vh]"
    >
      {skill && (
        <div className="-m-4 sm:-m-5 flex flex-col h-full">
          {skill.when_to_use && (
            <div className="shrink-0 px-5 py-3 border-b border-border/50">
              <p className="type-caption text-muted-foreground">{skill.when_to_use}</p>
            </div>
          )}

          <div className="flex-1 min-h-0 flex flex-col sm:flex-row">
            <div className="flex-1 min-h-0 min-w-0 overflow-y-auto p-5 skill-markdown-compact">
              {isLoading && (
                <div className="flex items-center gap-2 type-size-13 text-muted-foreground">
                  <SpinnerGap className="size-4 animate-spin" />
                  <span>Loading skill content...</span>
                </div>
              )}
              {!isLoading && error && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4">
                  <p className="type-size-13 font-medium text-destructive">Failed to load full skill content.</p>
                  <p className="mt-1 type-size-12 text-destructive/70">Try closing and reopening this skill.</p>
                </div>
              )}
              {!isLoading && !error && (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {detail?.content || "No skill content available."}
                </ReactMarkdown>
              )}
            </div>

            {skillFiles.length > 0 && (
              <div className="shrink-0 sm:w-64 border-t sm:border-t-0 sm:border-l border-border/50 overflow-y-auto">
                <p className="px-4 pt-4 pb-2 type-overline text-muted-foreground/50">Files</p>
                <div className="pb-3">
                  {groupFilesByFolder(skillFiles).map(({ folder, files }) => (
                    <div key={folder}>
                      {folder && (
                        <div className="flex items-center gap-2 px-4 pt-3 pb-1.5">
                          <FolderSimple className="size-3 shrink-0 text-muted-foreground/40" />
                          <span className="type-caption font-medium text-muted-foreground/60 truncate">{folder}</span>
                        </div>
                      )}
                      {files.map((file) => (
                        <button
                          key={file.path}
                          type="button"
                          onClick={() => {
                            void handleDownloadFile(skill.id, file);
                          }}
                          disabled={downloadingPaths.has(`${skill.id}:${file.path}`)}
                          className={cn(
                            "flex w-full items-center gap-2.5 py-2 text-left transition-colors hover:bg-muted/40",
                            downloadingPaths.has(`${skill.id}:${file.path}`) ? "opacity-70" : "",
                            folder ? "px-4 pl-9" : "px-4",
                          )}
                        >
                          {downloadingPaths.has(`${skill.id}:${file.path}`) ? (
                            <SpinnerGap className="size-3 shrink-0 animate-spin text-muted-foreground/40" />
                          ) : (
                            <DownloadSimple className="size-3 shrink-0 text-muted-foreground/40" />
                          )}
                          <span className="type-caption text-foreground truncate">{file.name}</span>
                          <span className="ml-auto shrink-0 type-nav-meta tabular-nums text-muted-foreground/40">
                            {formatBytes(file.size_bytes)}
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
