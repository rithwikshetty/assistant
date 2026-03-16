import * as React from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  X,
  SpinnerGap,
  FloppyDisk,
  Upload,
  Trash,
  FileText,
  Code,
  BookOpen,
  FolderOpen,
  CaretLeft,
  Circle,
} from "@phosphor-icons/react";

import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import {
  deleteCustomSkill,
  deleteCustomSkillFile,
  disableCustomSkill,
  getCustomSkillDetail,
  enableCustomSkill,
  saveCustomSkillReference,
  updateCustomSkill,
  uploadCustomSkillFile,
  type CustomSkillDetail,
  type SkillManifestFile,
  type SkillStatus,
} from "@/lib/api/skills";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { formatBytes } from "./skill-utils";

type EditorTab = "overview" | "instructions" | "references" | "files";

const TABS = [
  { id: "overview" as const, label: "Overview", icon: FileText },
  { id: "instructions" as const, label: "Instructions", icon: Code },
  { id: "references" as const, label: "References", icon: BookOpen },
  { id: "files" as const, label: "Files", icon: FolderOpen },
];

interface SkillEditorModalProps {
  skillId: string | null;
  onClose: () => void;
  onDeleted: () => void;
}

export function SkillEditorModal({ skillId, onClose, onDeleted }: SkillEditorModalProps) {
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  const [mounted, setMounted] = React.useState(false);
  const [animateMounted, setAnimateMounted] = React.useState(false);
  const [activeTab, setActiveTab] = React.useState<EditorTab>("overview");
  const [showMobileSidebar, setShowMobileSidebar] = React.useState(true);

  // Editor state
  const [editorTitle, setEditorTitle] = React.useState("");
  const [editorDescription, setEditorDescription] = React.useState("");
  const [editorWhenToUse, setEditorWhenToUse] = React.useState("");
  const [editorContent, setEditorContent] = React.useState("");
  const [editorStatus, setEditorStatus] = React.useState<SkillStatus>("disabled");
  const [editorFiles, setEditorFiles] = React.useState<SkillManifestFile[]>([]);
  const [editorUpdatedAt, setEditorUpdatedAt] = React.useState<string | undefined>(undefined);
  const [saveState, setSaveState] = React.useState<"idle" | "saving" | "saved" | "error">("idle");
  const [hydratedId, setHydratedId] = React.useState<string | null>(null);
  const [isActionBusy, setIsActionBusy] = React.useState(false);

  // Reference state
  const [referencePath, setReferencePath] = React.useState("references/module_a.md");
  const [referenceContent, setReferenceContent] = React.useState("");
  const [isSavingReference, setIsSavingReference] = React.useState(false);

  // Upload state
  const [uploadCategory, setUploadCategory] = React.useState<"references" | "assets" | "templates">("assets");
  const [uploadRelativePath, setUploadRelativePath] = React.useState("");
  const [uploadFile, setUploadFile] = React.useState<File | null>(null);
  const [isUploadingFile, setIsUploadingFile] = React.useState(false);

  const lastSavedRef = React.useRef<string>("");
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const open = Boolean(skillId);

  // Reset tab when opening
  React.useEffect(() => {
    if (open) {
      setActiveTab("overview");
      setShowMobileSidebar(true);
    }
  }, [open]);

  // Mount / animation lifecycle
  React.useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (open) document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  React.useEffect(() => {
    if (open) {
      const id = requestAnimationFrame(() => setAnimateMounted(true));
      return () => cancelAnimationFrame(id);
    } else {
      setAnimateMounted(false);
    }
  }, [open]);

  // Fetch skill detail
  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["skills", "custom", "detail", skillId || ""],
    queryFn: () => getCustomSkillDetail(skillId || ""),
    enabled: Boolean(skillId),
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  // Hydrate editor from fetched detail
  const applyDetail = React.useCallback((d: CustomSkillDetail) => {
    setEditorTitle(d.title || "");
    setEditorDescription(d.description || "");
    setEditorWhenToUse(d.when_to_use || "");
    setEditorContent(d.content || "");
    setEditorStatus(d.status);
    setEditorFiles(d.files || []);
    setEditorUpdatedAt(d.updated_at || undefined);
    setHydratedId(d.id);

    const snapshot = JSON.stringify({
      title: d.title || "",
      description: d.description || "",
      when_to_use: d.when_to_use || "",
      content: d.content || "",
    });
    lastSavedRef.current = snapshot;
    setSaveState("idle");
  }, []);

  React.useEffect(() => {
    if (detail) applyDetail(detail);
  }, [detail, applyDetail]);

  // Computed snapshot for auto-save diffing
  const snapshot = React.useMemo(
    () =>
      JSON.stringify({
        title: editorTitle,
        description: editorDescription,
        when_to_use: editorWhenToUse,
        content: editorContent,
      }),
    [editorContent, editorDescription, editorTitle, editorWhenToUse],
  );

  // Save handler
  const save = React.useCallback(async (): Promise<string | undefined | null> => {
    if (!skillId) return editorUpdatedAt;
    if (hydratedId !== skillId) return editorUpdatedAt;
    if (snapshot === lastSavedRef.current) return editorUpdatedAt;

    setSaveState("saving");
    try {
      const updated = await updateCustomSkill(skillId, {
        title: editorTitle,
        description: editorDescription,
        when_to_use: editorWhenToUse,
        content: editorContent,
        expected_updated_at: editorUpdatedAt,
      });
      applyDetail(updated);
      setSaveState("saved");
      queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
      void queryClient.invalidateQueries({ queryKey: ["skills", "custom"] });
      void queryClient.invalidateQueries({ queryKey: ["skills", "manifest"] });
      return updated.updated_at || undefined;
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please retry.";
      addToast({ type: "error", title: "Failed to save custom skill", description });
      setSaveState("error");
      return null;
    }
  }, [
    addToast,
    applyDetail,
    editorUpdatedAt,
    skillId,
    editorContent,
    editorDescription,
    snapshot,
    editorTitle,
    editorWhenToUse,
    hydratedId,
    queryClient,
  ]);

  // Debounced auto-save (900ms)
  React.useEffect(() => {
    if (!skillId || hydratedId !== skillId) return;
    if (snapshot === lastSavedRef.current) return;
    const timer = window.setTimeout(() => void save(), 900);
    return () => window.clearTimeout(timer);
  }, [skillId, snapshot, hydratedId, save]);

  // Action handlers
  const handleEnable = React.useCallback(async () => {
    if (!skillId) return;
    setIsActionBusy(true);
    try {
      const expectedUpdatedAt = await save();
      if (expectedUpdatedAt === null) return;
      const updated = await enableCustomSkill(skillId, expectedUpdatedAt);
      applyDetail(updated);
      queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills", "custom"] }),
        queryClient.invalidateQueries({ queryKey: ["skills", "manifest"] }),
      ]);
      addToast({ type: "success", title: "Skill enabled", description: "This skill is now available in chat." });
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: "Failed to enable skill", description });
    } finally {
      setIsActionBusy(false);
    }
  }, [addToast, applyDetail, skillId, queryClient, save]);

  const handleDisable = React.useCallback(async () => {
    if (!skillId) return;
    setIsActionBusy(true);
    try {
      const expectedUpdatedAt = await save();
      if (expectedUpdatedAt === null) return;
      const updated = await disableCustomSkill(skillId, expectedUpdatedAt);
      applyDetail(updated);
      queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills", "custom"] }),
        queryClient.invalidateQueries({ queryKey: ["skills", "manifest"] }),
      ]);
      addToast({ type: "success", title: "Skill disabled", description: "This skill is no longer available in chat." });
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: "Failed to disable skill", description });
    } finally {
      setIsActionBusy(false);
    }
  }, [addToast, applyDetail, skillId, queryClient, save]);

  const handleDelete = React.useCallback(async () => {
    if (!skillId) return;
    setIsActionBusy(true);
    try {
      await deleteCustomSkill(skillId);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills", "custom"] }),
        queryClient.invalidateQueries({ queryKey: ["skills", "manifest"] }),
      ]);
      addToast({ type: "success", title: "Custom skill deleted" });
      onDeleted();
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: "Failed to delete skill", description });
    } finally {
      setIsActionBusy(false);
    }
  }, [addToast, skillId, queryClient, onDeleted]);

  const handleUploadFile = React.useCallback(async () => {
    if (!skillId || !uploadFile) return;
    try {
      setIsUploadingFile(true);
      const updated = await uploadCustomSkillFile({
        skillId,
        category: uploadCategory,
        file: uploadFile,
        relativePath: uploadRelativePath || undefined,
      });
      applyDetail(updated);
      queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
      await queryClient.invalidateQueries({ queryKey: ["skills", "custom"] });
      setUploadFile(null);
      setUploadRelativePath("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      addToast({ type: "success", title: "File uploaded" });
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: "Couldn't upload file", description });
    } finally {
      setIsUploadingFile(false);
    }
  }, [addToast, applyDetail, skillId, queryClient, uploadCategory, uploadFile, uploadRelativePath]);

  const handleDeleteFile = React.useCallback(
    async (filePath: string) => {
      if (!skillId) return;
      try {
        const updated = await deleteCustomSkillFile({ skillId, filePath });
        applyDetail(updated);
        queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
        await queryClient.invalidateQueries({ queryKey: ["skills", "custom"] });
        addToast({ type: "success", title: "File removed" });
      } catch (err) {
        const description = err instanceof Error ? err.message : "Please try again.";
        addToast({ type: "error", title: "Couldn't delete file", description });
      }
    },
    [addToast, applyDetail, skillId, queryClient],
  );

  const handleSaveReference = React.useCallback(async () => {
    if (!skillId) return;
    try {
      setIsSavingReference(true);
      const updated = await saveCustomSkillReference({
        skillId,
        referencePath,
        content: referenceContent,
        expectedUpdatedAt: editorUpdatedAt,
      });
      applyDetail(updated);
      queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
      await queryClient.invalidateQueries({ queryKey: ["skills", "custom"] });
      addToast({ type: "success", title: "Reference saved" });
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: "Couldn't save reference", description });
    } finally {
      setIsSavingReference(false);
    }
  }, [addToast, applyDetail, skillId, editorUpdatedAt, queryClient, referenceContent, referencePath]);

  const handleTabClick = (tab: EditorTab) => {
    setActiveTab(tab);
    setShowMobileSidebar(false);
  };

  if (!open || !mounted) return null;

  const isReady = !isLoading && !error && hydratedId === skillId;

  return createPortal(
    <div
      className="fixed inset-0 z-[60] pointer-events-auto"
      role="dialog"
      aria-modal="true"
      aria-label="Edit Custom Skill"
    >
      {/* Backdrop */}
      <div
        className={cn(
          "absolute inset-0 bg-black/80 backdrop-blur-md transition-opacity duration-150 ease-out pointer-events-none",
          animateMounted ? "opacity-100" : "opacity-0",
        )}
        aria-hidden="true"
      />

      {/* Dialog container */}
      <div
        className="absolute inset-0 flex justify-center items-end sm:items-center p-0 sm:p-4"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <div
          className={cn(
            "z-[61] w-full h-[100dvh] sm:h-[82vh] sm:max-h-[780px] sm:max-w-5xl sm:rounded-2xl rounded-none",
            "border bg-background shadow-xl flex flex-col overflow-hidden",
            "transition-transform transition-opacity duration-150 ease-out",
            animateMounted
              ? "opacity-100 translate-y-0 sm:scale-100"
              : "opacity-0 translate-y-2 sm:translate-y-0 sm:scale-[0.98]",
          )}
          onClick={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
        >
          {/* Mobile Header */}
          <div className="sm:hidden flex items-center justify-between px-4 py-3 border-b">
            {!showMobileSidebar ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowMobileSidebar(true)}
                className="inline-flex items-center gap-1 type-size-14 text-muted-foreground hover:text-foreground h-auto px-2 py-1"
              >
                <CaretLeft className="size-4" />
                Back
              </Button>
            ) : (
              <h3 className="type-size-16 font-semibold truncate">
                {editorTitle || "Custom Skill"}
              </h3>
            )}
            <div className="flex items-center gap-2">
              <SaveIndicator state={saveState} />
              <Button
                variant="ghost"
                size="icon"
                aria-label="Close"
                onClick={onClose}
                className="size-8 rounded-lg hover:bg-muted"
              >
                <X className="size-4" />
              </Button>
            </div>
          </div>

          {/* Loading / Error */}
          {(isLoading || error) && (
            <div className="flex-1 flex items-center justify-center p-8">
              {isLoading && (
                <div className="flex items-center gap-2 type-size-13 text-muted-foreground">
                  <SpinnerGap className="size-4 animate-spin" />
                  <span>Loading custom skill...</span>
                </div>
              )}
              {!isLoading && error && (
                <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 max-w-md">
                  <p className="type-size-13 font-medium text-destructive">Failed to load custom skill.</p>
                  <p className="mt-1 type-size-12 text-destructive/70">Try closing and reopening this editor.</p>
                </div>
              )}
            </div>
          )}

          {/* Main layout */}
          {isReady && (
            <div className="flex flex-1 overflow-hidden">
              {/* Sidebar */}
              <aside
                className={cn(
                  "w-full sm:w-52 shrink-0 border-r bg-muted/30 overflow-y-auto flex flex-col",
                  "sm:block",
                  showMobileSidebar ? "block" : "hidden",
                )}
              >
                {/* Desktop: close button */}
                <div className="hidden sm:flex items-center justify-between px-4 pt-4 pb-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Close"
                    onClick={onClose}
                    className="size-8 rounded-lg hover:bg-muted"
                  >
                    <X className="size-4" />
                  </Button>
                  <SaveIndicator state={saveState} />
                </div>

                {/* Tab nav */}
                <nav className="p-3 sm:pt-2 flex-1">
                  {TABS.map((tab) => {
                    const Icon = tab.icon;
                    const isActive = activeTab === tab.id;
                    return (
                      <Button
                        key={tab.id}
                        variant="ghost"
                        onClick={() => handleTabClick(tab.id)}
                        className={cn(
                          "w-full flex items-center justify-start gap-3 px-3 py-2.5 rounded-lg type-size-14 font-medium transition-colors h-auto",
                          isActive
                            ? "bg-primary/10 text-primary dark:bg-primary/15"
                            : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        )}
                      >
                        <Icon className="size-[18px]" />
                        {tab.label}
                      </Button>
                    );
                  })}
                </nav>

                {/* Bottom actions */}
                <div className="px-4 py-3 border-t border-border/40 mt-auto flex items-center justify-between">
                  <DeleteIconButton disabled={isActionBusy} onConfirm={handleDelete} />
                  <Switch
                    checked={editorStatus === "enabled"}
                    disabled={isActionBusy}
                    onCheckedChange={(checked) => {
                      if (checked) void handleEnable();
                      else void handleDisable();
                    }}
                  />
                </div>
              </aside>

              {/* Content area */}
              <main
                className={cn(
                  "flex-1 overflow-y-auto",
                  "sm:block",
                  showMobileSidebar ? "hidden sm:block" : "block",
                )}
              >
                <div className="p-5 sm:p-6">
                  {activeTab === "overview" && (
                    <OverviewTab
                      title={editorTitle}
                      onTitleChange={setEditorTitle}
                      description={editorDescription}
                      onDescriptionChange={setEditorDescription}
                      whenToUse={editorWhenToUse}
                      onWhenToUseChange={setEditorWhenToUse}
                      status={editorStatus}
                    />
                  )}
                  {activeTab === "instructions" && (
                    <InstructionsTab
                      content={editorContent}
                      onContentChange={setEditorContent}
                    />
                  )}
                  {activeTab === "references" && (
                    <ReferencesTab
                      referencePath={referencePath}
                      onReferencePathChange={setReferencePath}
                      referenceContent={referenceContent}
                      onReferenceContentChange={setReferenceContent}
                      isSaving={isSavingReference}
                      onSave={() => void handleSaveReference()}
                    />
                  )}
                  {activeTab === "files" && (
                    <FilesTab
                      files={editorFiles}
                      uploadCategory={uploadCategory}
                      onUploadCategoryChange={setUploadCategory}
                      uploadRelativePath={uploadRelativePath}
                      onUploadRelativePathChange={setUploadRelativePath}
                      uploadFile={uploadFile}
                      onUploadFileChange={setUploadFile}
                      fileInputRef={fileInputRef}
                      isUploading={isUploadingFile}
                      onUpload={() => void handleUploadFile()}
                      onDeleteFile={(path) => void handleDeleteFile(path)}
                    />
                  )}
                </div>
              </main>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

function SaveIndicator({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  if (state === "idle") return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 type-size-12",
        state === "saving" && "text-muted-foreground",
        state === "saved" && "text-muted-foreground/70",
        state === "error" && "text-destructive",
      )}
    >
      {state === "saving" && <SpinnerGap className="size-3 animate-spin" />}
      {state === "saving" && "Saving..."}
      {state === "saved" && "Saved"}
      {state === "error" && "Save failed"}
    </span>
  );
}

function DeleteIconButton({ disabled, onConfirm }: { disabled?: boolean; onConfirm: () => Promise<void> }) {
  const [stage, setStage] = React.useState<"idle" | "confirm" | "loading">("idle");
  const timerRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (stage === "confirm") {
      timerRef.current = window.setTimeout(() => setStage("idle"), 4000);
    }
    return () => { if (timerRef.current) window.clearTimeout(timerRef.current); };
  }, [stage]);

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      disabled={disabled || stage === "loading"}
      className={cn(
        "h-7 px-2 type-size-12 gap-1.5 rounded-lg",
        stage === "confirm"
          ? "bg-destructive/10 text-destructive hover:bg-destructive/20 hover:text-destructive"
          : "text-muted-foreground/50 hover:text-destructive",
      )}
      onClick={async () => {
        if (stage === "idle") { setStage("confirm"); return; }
        if (stage === "confirm") {
          setStage("loading");
          try { await onConfirm(); } finally { setStage("idle"); }
        }
      }}
    >
      {stage === "loading" ? <SpinnerGap className="size-3 animate-spin" /> : <Trash className="size-3" />}
      Delete
    </Button>
  );
}

function StatusBadge({ status }: { status: SkillStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 font-medium",
        status === "enabled"
          ? "border-emerald-600/30 text-emerald-700 dark:border-emerald-400/30 dark:text-emerald-400"
          : "border-amber-600/30 text-amber-700 dark:border-amber-400/30 dark:text-amber-400",
      )}
    >
      <Circle
        className={cn(
          "size-2",
          status === "enabled"
            ? "fill-emerald-600 text-emerald-600 dark:fill-emerald-400 dark:text-emerald-400"
            : "fill-amber-600 text-amber-600 dark:fill-amber-400 dark:text-amber-400",
        )}
      />
      {status === "enabled" ? "Enabled" : "Disabled"}
    </Badge>
  );
}

function FieldLabel({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block type-size-14 font-medium text-foreground mb-1.5">
      {children}
    </label>
  );
}

function FieldHint({ children }: { children: React.ReactNode }) {
  return <p className="type-size-12 text-muted-foreground mt-1.5">{children}</p>;
}

// ---------------------------------------------------------------------------
// Tab content
// ---------------------------------------------------------------------------

function OverviewTab({
  title,
  onTitleChange,
  description,
  onDescriptionChange,
  whenToUse,
  onWhenToUseChange,
  status,
}: {
  title: string;
  onTitleChange: (v: string) => void;
  description: string;
  onDescriptionChange: (v: string) => void;
  whenToUse: string;
  onWhenToUseChange: (v: string) => void;
  status: SkillStatus;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">Overview</h2>
        <p className="type-size-14 text-muted-foreground">
          Core details about this custom skill
        </p>
      </div>

      {/* Status */}
      <div className="flex items-center gap-3">
        <StatusBadge status={status} />
      </div>

      {/* Title */}
      <section className="space-y-1.5">
        <FieldLabel>Title</FieldLabel>
        <Input value={title} onChange={(e) => onTitleChange(e.target.value)} placeholder="e.g. Cost Estimation Workflow" />
        <FieldHint>A short name shown in the skill list and chat.</FieldHint>
      </section>

      {/* When to use */}
      <section className="space-y-1.5">
        <FieldLabel>When to use</FieldLabel>
        <Textarea
          value={whenToUse}
          onChange={(e) => onWhenToUseChange(e.target.value)}
          rows={2}
          className="resize-y min-h-[56px]"
          placeholder="e.g. Call when a user asks about construction rates, historical pricing, or BCIS adjustments."
        />
        <FieldHint>Tells the AI when to activate this skill. Be specific about triggers.</FieldHint>
      </section>

      {/* Description */}
      <section className="space-y-1.5">
        <FieldLabel>Description</FieldLabel>
        <Textarea
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          rows={3}
          className="resize-y min-h-[76px]"
          placeholder="e.g. NRM Stage 2 cost planning workflow with modules for Cost Plan, Value Engineering, and Risk Register."
        />
        <FieldHint>Shown under the title in the skill card. 1-2 sentences.</FieldHint>
      </section>
    </div>
  );
}

function InstructionsTab({
  content,
  onContentChange,
}: {
  content: string;
  onContentChange: (v: string) => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">Instructions</h2>
        <p className="type-size-14 text-muted-foreground">
          Markdown injected into the conversation when this skill activates.
        </p>
      </div>

      <Textarea
        value={content}
        onChange={(e) => onContentChange(e.target.value)}
        rows={20}
        className="font-mono type-size-13 resize-y min-h-[360px]"
        placeholder="# Skill Name&#10;&#10;Write the full skill instructions in Markdown..."
      />

    </div>
  );
}

function ReferencesTab({
  referencePath,
  onReferencePathChange,
  referenceContent,
  onReferenceContentChange,
  isSaving,
  onSave,
}: {
  referencePath: string;
  onReferencePathChange: (v: string) => void;
  referenceContent: string;
  onReferenceContentChange: (v: string) => void;
  isSaving: boolean;
  onSave: () => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="type-size-20 font-semibold text-foreground mb-1">References</h2>
        <p className="type-size-14 text-muted-foreground">
          Save reference notes as <code className="type-size-13 bg-muted rounded px-1.5 py-0.5">references/*.md</code> files for modular <code className="type-size-13 bg-muted rounded px-1.5 py-0.5">load_skill</code> usage.
        </p>
      </div>

      <section className="space-y-4">
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <FieldLabel>Module path</FieldLabel>
            <Input
              value={referencePath}
              onChange={(e) => onReferencePathChange(e.target.value)}
              placeholder="references/module_a.md"
            />
          </div>
          <Button type="button" variant="outline" onClick={onSave} disabled={isSaving}>
            {isSaving ? <SpinnerGap className="size-4 animate-spin" /> : <FloppyDisk className="size-3.5" />}
            Save reference
          </Button>
        </div>

        <div>
          <FieldLabel>Content</FieldLabel>
          <Textarea
            value={referenceContent}
            onChange={(e) => onReferenceContentChange(e.target.value)}
            rows={12}
            className="font-mono type-size-13 resize-y min-h-[200px]"
            placeholder="# Module A&#10;&#10;Steps, rules, examples..."
          />
        </div>
      </section>
    </div>
  );
}

function FilesTab({
  files,
  uploadCategory,
  onUploadCategoryChange,
  uploadRelativePath,
  onUploadRelativePathChange,
  uploadFile,
  onUploadFileChange,
  fileInputRef,
  isUploading,
  onUpload,
  onDeleteFile,
}: {
  files: SkillManifestFile[];
  uploadCategory: "references" | "assets" | "templates";
  onUploadCategoryChange: (v: "references" | "assets" | "templates") => void;
  uploadRelativePath: string;
  onUploadRelativePathChange: (v: string) => void;
  uploadFile: File | null;
  onUploadFileChange: (f: File | null) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  isUploading: boolean;
  onUpload: () => void;
  onDeleteFile: (path: string) => void;
}) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="type-size-20 font-semibold text-foreground mb-1">Files</h2>
          <p className="type-size-14 text-muted-foreground">
            Upload references, assets, or templates scoped to this skill.
          </p>
        </div>
        <span className="type-size-12 text-muted-foreground/60 tabular-nums shrink-0">
          {files.length} file{files.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Upload */}
      <section className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <FieldLabel>Category</FieldLabel>
            <Select value={uploadCategory} onValueChange={(v) => onUploadCategoryChange(v as "references" | "assets" | "templates")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="assets">assets</SelectItem>
                <SelectItem value="templates">templates</SelectItem>
                <SelectItem value="references">references</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <FieldLabel>Relative path <span className="text-muted-foreground font-normal">(optional)</span></FieldLabel>
            <Input
              value={uploadRelativePath}
              onChange={(e) => onUploadRelativePathChange(e.target.value)}
              placeholder="subfolder/name.ext"
            />
          </div>
        </div>

        <div
          className={cn(
            "flex items-center gap-3 rounded-xl border border-dashed border-border/50 px-4 py-3 cursor-pointer transition-colors",
            "hover:border-border hover:bg-muted/30",
            uploadFile && "border-solid border-border/60 bg-muted/20",
          )}
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload className="size-4 shrink-0 text-muted-foreground/50" />
          <span className="type-size-14 text-muted-foreground truncate flex-1">
            {uploadFile ? uploadFile.name : "Choose a file..."}
          </span>
          <input
            ref={fileInputRef}
            type="file"
            onChange={(e) => onUploadFileChange(e.target.files?.[0] || null)}
            className="sr-only"
          />
          <Button
            type="button"
            size="sm"
            disabled={!uploadFile || isUploading}
            onClick={(e) => { e.stopPropagation(); onUpload(); }}
          >
            {isUploading ? <SpinnerGap className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
            Upload
          </Button>
        </div>
      </section>

      {/* File list */}
      <section className="space-y-2">
        {files.length === 0 ? (
          <p className="py-8 text-center type-size-14 text-muted-foreground/50">No files yet</p>
        ) : (
          <ul className="space-y-1">
            {files.map((file) => {
              const isMaster = file.path === "SKILL.md";
              return (
                <li key={file.path} className="flex items-center gap-2 rounded-lg p-2 transition-colors hover:bg-muted/30">
                  <FileText className="size-4 shrink-0 text-muted-foreground/40" />
                  <div className="flex-1 min-w-0">
                    <p className="type-size-14 text-foreground truncate">{file.path}</p>
                    <p className="type-size-12 text-muted-foreground/60">
                      {file.category} · {formatBytes(file.size_bytes)}
                    </p>
                  </div>
                  {!isMaster && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-7 shrink-0 text-muted-foreground/40 hover:text-destructive"
                      onClick={() => onDeleteFile(file.path)}
                    >
                      <Trash className="size-3.5" />
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
