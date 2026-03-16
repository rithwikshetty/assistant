import { useState, useEffect, useRef, useCallback } from "react";
import { FolderSimple } from "@phosphor-icons/react";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { updateProject, getProject } from "@/lib/api/projects-core";
import { useProjects } from "@/hooks/use-projects";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ProjectWithConversationCount, Project } from "@/lib/api/projects-core";

const MAX_NAME_LENGTH = 50;

const PROJECT_COLORS = [
  { name: "Blue", value: "#3B82F6" },
  { name: "Indigo", value: "#6366F1" },
  { name: "Violet", value: "#8B5CF6" },
  { name: "Fuchsia", value: "#D946EF" },
  { name: "Pink", value: "#EC4899" },
  { name: "Rose", value: "#F43F5E" },
  { name: "Orange", value: "#F97316" },
  { name: "Amber", value: "#F59E0B" },
  { name: "Emerald", value: "#10B981" },
  { name: "Slate", value: "#64748B" },
];

interface EditProjectDialogProps {
  open: boolean;
  onClose: () => void;
  project: ProjectWithConversationCount | null;
}

export function EditProjectDialog({ open, onClose, project }: EditProjectDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [customInstructions, setCustomInstructions] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [hydratedProject, setHydratedProject] = useState<Project | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const lastSaved = useRef<{
    name: string;
    description: string;
    customInstructions: string;
    color: string | null;
  } | null>(null);
  const { addToast } = useToast();
  const { updateProjects } = useProjects();

  const activeProject = hydratedProject ?? project;

  useEffect(() => {
    if (!open || !project?.id) {
      setHydratedProject(null);
      setHydrating(false);
      setSaveState("idle");
      lastSaved.current = null;
      return;
    }

    let cancelled = false;

    (async () => {
      if (hydratedProject && hydratedProject.id === project.id) {
        return;
      }

      setHydrating(true);
      try {
        const fresh = await getProject(project.id);
        if (!cancelled) {
          setHydratedProject(fresh);
        }
      } catch (error) {
        if (!cancelled) {
          setHydratedProject(null);
          addToast({
            type: "error",
            title: "Couldn't load project details",
            description: error instanceof Error ? error.message : "Please try again.",
          });
        }
      } finally {
        if (!cancelled) {
          setHydrating(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, project?.id, hydratedProject, addToast]);

  useEffect(() => {
    if (!open || !activeProject) return;

    setName(activeProject.name ?? "");
    setDescription(activeProject.description || "");
    setCustomInstructions(activeProject.custom_instructions || "");
    setColor(activeProject.color ?? null);
    lastSaved.current = {
      name: activeProject.name ?? "",
      description: activeProject.description || "",
      customInstructions: activeProject.custom_instructions || "",
      color: activeProject.color ?? null,
    };
    setSaveState("idle");
  }, [open, activeProject]);

  const trimmedName = name.trim();
  const nameLength = trimmedName.length;
  const overNameLimit = nameLength > MAX_NAME_LENGTH;

  const applyProjectPatch = useCallback(
    (patch: Partial<Project> & { id: string }) => {
      setHydratedProject((prev) => {
        if (prev && prev.id === patch.id) {
          return { ...prev, ...patch };
        }
        if (!prev && project && project.id === patch.id) {
          return { ...(project as Project), ...patch };
        }
        return prev;
      });

      updateProjects((current) =>
        current.map((item) => {
          if (item.id !== patch.id) return item;
          return {
            ...item,
            name: patch.name ?? item.name,
            description: patch.description === undefined ? item.description : patch.description,
            custom_instructions:
              patch.custom_instructions === undefined ? item.custom_instructions : patch.custom_instructions,
            color: patch.color === undefined ? item.color : patch.color,
            updated_at: patch.updated_at ?? item.updated_at,
          };
        }),
      );

      try {
        window.dispatchEvent(new CustomEvent("frontend:projectUpdated", { detail: { project: patch } }));
      } catch {}
    },
    [project, updateProjects],
  );

  const saveIfChanged = useCallback(async () => {
    const targetProject = activeProject;
    if (!targetProject) return;

    if (!trimmedName || overNameLimit) {
      setSaveState("error");
      return;
    }

    const snapshot = {
      name: trimmedName,
      description: description.trim(),
      customInstructions: customInstructions.trim(),
      color,
    };

    if (
      lastSaved.current &&
      lastSaved.current.name === snapshot.name &&
      lastSaved.current.description === snapshot.description &&
      lastSaved.current.customInstructions === snapshot.customInstructions &&
      lastSaved.current.color === snapshot.color
    ) {
      return;
    }

    setUpdating(true);
    setSaveState("saving");

    try {
      const updatedProject = await updateProject(targetProject.id, {
        name: snapshot.name,
        description: snapshot.description,
        custom_instructions: snapshot.customInstructions,
        color: snapshot.color || undefined,
      });

      applyProjectPatch(updatedProject);
      lastSaved.current = snapshot;
      setSaveState("saved");
    } catch (error) {
      addToast({
        type: "error",
        title: "Failed to update project",
        description: error instanceof Error ? error.message : "An error occurred",
      });
      setSaveState("error");
    } finally {
      setUpdating(false);
    }
  }, [
    activeProject,
    addToast,
    applyProjectPatch,
    color,
    customInstructions,
    description,
    overNameLimit,
    trimmedName,
  ]);

  const handleClose = () => {
    setName("");
    setDescription("");
    setCustomInstructions("");
    setColor(null);
    setHydratedProject(null);
    setHydrating(false);
    setSaveState("idle");
    lastSaved.current = null;
    onClose();
  };

  useEffect(() => {
    if (!open || !activeProject) return;
    const timer = window.setTimeout(() => {
      void saveIfChanged();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [open, activeProject, name, description, customInstructions, color, saveIfChanged]);

  return (
    <Modal open={open} onClose={handleClose} title="Edit Project">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void saveIfChanged();
        }}
        className="space-y-4"
        aria-busy={hydrating || undefined}
      >
        <div className="flex items-center justify-end type-size-10 text-muted-foreground gap-2">
          {saveState === "saving" && <span>Saving…</span>}
          {saveState === "saved" && <span className="text-foreground/80">Saved</span>}
          {saveState === "error" && <span className="text-destructive">Save failed</span>}
        </div>

        {hydrating && (
          <div className="rounded-md border border-border/40 bg-muted/20 px-3 py-2 type-size-12 text-muted-foreground">
            Loading latest project details…
          </div>
        )}

        <div>
          <label htmlFor="project-name" className="block type-size-14 font-medium text-foreground mb-1.5">
            Project name <span className="text-destructive">*</span>
          </label>
          <Input
            id="project-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Office Renovation Q1 2025"
            disabled={hydrating}
            autoFocus
          />
          <div className="mt-1 flex items-center justify-between type-size-12">
            <span className={cn("transition-colors", overNameLimit ? "text-destructive" : "text-muted-foreground")}>
              {overNameLimit ? `Project names are limited to ${MAX_NAME_LENGTH} characters.` : "\u00a0"}
            </span>
            <span className={cn("font-medium", overNameLimit ? "text-destructive" : "text-muted-foreground")}>
              {nameLength} / {MAX_NAME_LENGTH}
            </span>
          </div>
        </div>

        <div>
          <label htmlFor="project-description" className="block type-size-14 font-medium text-foreground mb-1.5">
            Description <span className="type-size-12 text-muted-foreground">(optional)</span>
          </label>
          <Textarea
            id="project-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief description of the project..."
            disabled={hydrating}
            rows={6}
            className="resize-y min-h-[160px]"
            maxLength={5000}
          />
          <div className="mt-1 type-size-12 text-muted-foreground text-right">
            {description.length} / 5000
          </div>
        </div>

        <div>
          <label htmlFor="custom-instructions" className="block type-size-14 font-medium text-foreground mb-1.5">
            Custom Instructions <span className="type-size-12 text-muted-foreground">(optional)</span>
          </label>
          <p className="type-size-12 text-muted-foreground mb-2">
            Guide how the AI responds in this project. These instructions are visible to all members.
          </p>
          <Textarea
            id="custom-instructions"
            value={customInstructions}
            onChange={(e) => setCustomInstructions(e.target.value)}
            placeholder="e.g., Focus on cost analysis and value engineering. Always include risk assessments..."
            disabled={hydrating}
            rows={8}
            className="resize-y min-h-[200px]"
            maxLength={2000}
          />
          <div className="mt-1 type-size-12 text-muted-foreground text-right">
            {customInstructions.length} / 2000
          </div>
        </div>

        <div>
          <label className="block type-size-14 font-medium text-foreground mb-2">
            Icon color <span className="type-size-12 text-muted-foreground">(optional)</span>
          </label>
          <div className="flex gap-1.5">
            {PROJECT_COLORS.map((colorOption) => (
              <Button
                key={colorOption.value}
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setColor(colorOption.value === color ? null : colorOption.value)}
                disabled={hydrating || updating}
                className={cn(
                  "size-8 p-1.5 rounded-lg transition-all focus:outline-none focus:ring-2 focus:ring-primary/20",
                  color === colorOption.value
                    ? "bg-muted ring-2 ring-foreground/20"
                    : "hover:bg-muted/50",
                )}
                aria-label={`${colorOption.name} color`}
                aria-pressed={color === colorOption.value}
              >
                <FolderSimple className="size-5" style={{ color: colorOption.value }} />
              </Button>
            ))}
          </div>
        </div>
      </form>
    </Modal>
  );
}
