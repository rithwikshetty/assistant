
import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import type { ChangeEvent } from "react";
import { FolderSimple, Users, Image as ImageIcon, SpinnerGap } from "@phosphor-icons/react";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PROJECT_CATEGORY_OPTIONS } from "@/lib/project-categories";
import { updateProject, getProject, uploadProjectPublicImage, deleteProjectPublicImage } from "@/lib/api/projects-core";
import { getBackendBaseUrl } from "@/lib/utils/backend-url";
import { fetchWithAuth } from "@/lib/api/auth";
import { useProjects } from "@/hooks/use-projects";
import { cn } from "@/lib/utils";
import { DEFAULT_PROJECT_IMAGE_SRC } from "@/lib/projects/constants";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmButton } from "@/components/ui/confirm-button";
import type { ProjectWithConversationCount, Project } from "@/lib/api/projects-core";

const MAX_NAME_LENGTH = 50;

const CACHE_BUSTER_PARAM = "cb";

function withCacheBuster(url?: string | null, updatedAt?: string | null): string | null {
  if (!url) return null;
  const stamp = updatedAt ? Math.floor(new Date(updatedAt).getTime() / 1000) : Date.now();
  try {
    const parsed = new URL(url);
    parsed.searchParams.set(CACHE_BUSTER_PARAM, String(stamp));
    return parsed.toString();
  } catch {
    const separator = url.includes("?") ? "&" : "?";
    return `${url}${separator}${CACHE_BUSTER_PARAM}=${stamp}`;
  }
}

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
  const [category, setCategory] = useState<string | null>(null);
  const [isPublic, setIsPublic] = useState<boolean>(false);
  const [updating, setUpdating] = useState(false);
  const [hydratedProject, setHydratedProject] = useState<Project | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [imagePending, setImagePending] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const lastSaved = useRef<{
    name: string;
    description: string;
    customInstructions: string;
    color: string | null;
    category: string | null;
    isPublic: boolean;
  } | null>(null);
  const { addToast } = useToast();
  const { updateProjects } = useProjects();
  const API_BASE_URL = getBackendBaseUrl();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const activeProject = hydratedProject ?? project;

  // Only projects marked as public candidates (created via admin panel) can toggle visibility
  const canToggleVisibility = Boolean(activeProject?.is_public_candidate);
  const heroImageUrl = useMemo(() => {
    if (!activeProject) return null;
    return withCacheBuster(activeProject.public_image_url ?? null, activeProject.public_image_updated_at ?? null);
  }, [activeProject]);
  const heroAlt = heroImageUrl ? "Project image preview" : "Default project image";
  const heroSrc = heroImageUrl ?? DEFAULT_PROJECT_IMAGE_SRC;

  // Hydrate the project with the latest details when the dialog opens
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
      // Avoid refetching if we already loaded this project during this session
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

  // Pre-populate form fields once we have an active project
  useEffect(() => {
    if (!open) return;
    if (!activeProject) return;

    setName(activeProject.name ?? "");
    setDescription(activeProject.description || "");
    setCustomInstructions(activeProject.custom_instructions || "");
    setColor(activeProject.color ?? null);
    setCategory(activeProject.category ?? null);
    setIsPublic(Boolean(activeProject.is_public));
    lastSaved.current = {
      name: activeProject.name ?? "",
      description: activeProject.description || "",
      customInstructions: activeProject.custom_instructions || "",
      color: activeProject.color ?? null,
      category: activeProject.category ?? null,
      isPublic: Boolean(activeProject.is_public),
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
        current.map((p) => {
          if (p.id !== patch.id) return p;
          return {
            ...p,
            name: patch.name ?? p.name,
            description: patch.description === undefined ? p.description : patch.description,
            custom_instructions:
              patch.custom_instructions === undefined ? p.custom_instructions : patch.custom_instructions,
            color: patch.color === undefined ? p.color : patch.color,
            category:
              patch.category === undefined
                ? p.category ?? null
                : patch.category === null
                ? null
                : patch.category,
            is_public:
              patch.is_public === undefined ? p.is_public : Boolean(patch.is_public),
            public_image_url:
              patch.public_image_url === undefined ? p.public_image_url ?? null : patch.public_image_url ?? null,
            public_image_updated_at:
              patch.public_image_updated_at === undefined
                ? p.public_image_updated_at ?? null
                : patch.public_image_updated_at ?? null,
            updated_at: patch.updated_at ?? p.updated_at,
          };
        })
      );

      try {
        window.dispatchEvent(new CustomEvent("frontend:projectUpdated", { detail: { project: patch } }));
      } catch {}
    },
    [project, updateProjects]
  );

  const handleRequestImageUpload = useCallback(() => {
    if (imagePending || hydrating || updating || !activeProject) return;
    fileInputRef.current?.click();
  }, [activeProject, hydrating, imagePending, updating]);

  const handleImageFileChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file || !activeProject) {
        event.target.value = "";
        return;
      }
      setImagePending(true);
      try {
        const updated = await uploadProjectPublicImage(activeProject.id, file);
        applyProjectPatch(updated);
        addToast({ type: "success", title: "Image updated", description: "New hero image saved." });
      } catch (error) {
        addToast({
          type: "error",
          title: "Upload failed",
          description: error instanceof Error ? error.message : "Please try again.",
        });
      } finally {
        setImagePending(false);
        event.target.value = "";
      }
    },
    [activeProject, addToast, applyProjectPatch]
  );

  const handleRemoveImage = useCallback(async () => {
    if (imagePending || hydrating || updating || !activeProject || !heroImageUrl) return;
    setImagePending(true);
    try {
      const updated = await deleteProjectPublicImage(activeProject.id);
      applyProjectPatch(updated);
      addToast({
        type: "info",
        title: "Image removed",
        description: "We'll use the initial until you upload a new image.",
      });
    } catch (error) {
      addToast({
        type: "error",
        title: "Failed to remove image",
        description: error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      setImagePending(false);
    }
  }, [activeProject, addToast, applyProjectPatch, heroImageUrl, hydrating, imagePending, updating]);

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
      category: category ? category.trim() : null,
      isPublic,
    };

    if (lastSaved.current) {
      const prev = lastSaved.current;
      if (
        prev.name === snapshot.name &&
        prev.description === snapshot.description &&
        prev.customInstructions === snapshot.customInstructions &&
        prev.color === snapshot.color &&
        prev.category === snapshot.category &&
        prev.isPublic === snapshot.isPublic
      ) {
        return;
      }
    }

    setUpdating(true);
    setSaveState("saving");

    try {
      // Update metadata (name/description/custom_instructions/color/category)
      const updatedProject = await updateProject(targetProject.id, {
        name: snapshot.name,
        description: snapshot.description,
        custom_instructions: snapshot.customInstructions,
        color: snapshot.color || undefined,
        category: snapshot.category,
      });

      applyProjectPatch(updatedProject);

      // Toggle visibility if changed
      if (Boolean(targetProject.is_public) !== snapshot.isPublic) {
        if (snapshot.isPublic) {
          // Require description and category client-side as well
          if (
            !updatedProject.description ||
            !updatedProject.description.trim() ||
            !updatedProject.category ||
            !updatedProject.category.trim()
          ) {
            addToast({
              type: "error",
              title: "Missing details",
              description: "Add a description and select a category before making public.",
            });
            setSaveState("error");
            setUpdating(false);
            return;
          }
        }

        const res = await fetchWithAuth(`${API_BASE_URL}/projects/${targetProject.id}/visibility`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_public: snapshot.isPublic }),
        });
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(text || `Failed to update visibility (${res.status})`);
        }

        applyProjectPatch({ id: targetProject.id, is_public: snapshot.isPublic });
      }

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
    category,
    color,
    customInstructions,
    description,
    isPublic,
    overNameLimit,
    trimmedName,
    API_BASE_URL,
  ]);

  const handleClose = () => {
    setName("");
    setDescription("");
    setCustomInstructions("");
    setColor(null);
    setCategory(null);
    setIsPublic(false);
    setHydratedProject(null);
    setHydrating(false);
    setSaveState("idle");
    lastSaved.current = null;
    onClose();
  };

  // Debounced auto-save on field changes
  useEffect(() => {
    if (!open || !activeProject) return;
    const timer = window.setTimeout(() => {
      void saveIfChanged();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [open, activeProject, name, description, customInstructions, color, category, isPublic, saveIfChanged]);

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
            <span className={cn(
              "transition-colors",
              overNameLimit ? "text-destructive" : "text-muted-foreground"
            )}>
              {overNameLimit ? `Project names are limited to ${MAX_NAME_LENGTH} characters.` : "\u00a0"}
            </span>
            <span className={cn(
              "font-medium",
              overNameLimit ? "text-destructive" : "text-muted-foreground"
            )}>
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

        {canToggleVisibility && (
          <div className="space-y-5">
            <div className="space-y-1">
              <span className="type-size-10 font-semibold uppercase tracking-[0.08em] text-muted-foreground/80">
                Public project settings
              </span>
              <p className="type-size-12 text-muted-foreground">
                These options control how the project appears in the public browse view.
              </p>
            </div>

            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <Users className="size-4 text-muted-foreground" aria-hidden />
                <h4 className="type-size-14 font-semibold text-foreground">Project visibility</h4>
              </div>
              <div className="flex flex-col gap-3 rounded-xl border border-border/60 bg-muted/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <p className="type-size-14 font-medium text-foreground">{isPublic ? "Public" : "Private (not listed)"}</p>
                  <p className="type-size-12 text-muted-foreground">
                    {isPublic
                      ? "Anyone in your org can find and join."
                      : "Only invited members can access until you publish."}
                  </p>
                  <p className="type-size-10 text-muted-foreground/80">Changes auto-save after you edit.</p>
                </div>
                  <ConfirmButton
                    aria-label={isPublic ? "Make project private" : "Publish project"}
                    variant={isPublic ? "secondary" : "ghost"}
                    confirmVariant={isPublic ? "destructive" : "default"}
                    confirmLabel={isPublic ? "Confirm unpublish" : "Confirm publish"}
                    disabled={hydrating}
                    onConfirm={() => setIsPublic((prev) => !prev)}
                  >
                  {isPublic ? "Make private" : "Publish"}
                </ConfirmButton>
              </div>
            </section>

            <div className="space-y-4">
              <div>
                <label htmlFor="project-category" className="block type-size-14 font-medium text-foreground mb-1.5">
                  Category
                </label>
                <Select value={category ?? '__none__'} onValueChange={(v) => setCategory(v === '__none__' ? null : v)}>
                  <SelectTrigger id="project-category" className="h-9" disabled={hydrating}>
                    <SelectValue placeholder="— None —" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">— None —</SelectItem>
                    {PROJECT_CATEGORY_OPTIONS.map((option) => (
                      <SelectItem key={option} value={option}>{option}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <ImageIcon className="size-4 text-muted-foreground" aria-hidden />
                  <h4 className="type-size-14 font-semibold text-foreground">Project image</h4>
                </div>
                <div className="rounded-2xl border border-border/60 bg-muted/10 p-4 sm:p-5">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-5">
                    <div className="flex flex-col items-center gap-3 sm:items-start">
                      <div className="relative flex h-20 w-20 items-center justify-center overflow-hidden rounded-2xl border border-border/40 bg-muted/40 type-size-24 font-semibold text-muted-foreground sm:h-24 sm:w-24">
                        <img
                          src={heroSrc}
                          alt={heroAlt}
                          className="absolute inset-0 h-full w-full object-cover"
                        />
                      </div>
                      <div className="flex w-full flex-wrap items-center justify-center gap-2 sm:justify-start">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={handleRequestImageUpload}
                          disabled={imagePending || hydrating || updating || !activeProject}
                        >
                          {imagePending ? <SpinnerGap className="h-4 w-4 animate-spin" aria-hidden /> : "Upload image"}
                        </Button>
                        {heroImageUrl ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="text-destructive"
                            onClick={handleRemoveImage}
                            disabled={imagePending || hydrating || updating}
                          >
                            Remove
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    <p className="type-size-14 leading-relaxed text-muted-foreground sm:leading-relaxed">
                      Upload a square image (PNG, JPG, WebP, or GIF up to 2&nbsp;MB). It appears on the public browse card and helps teammates spot this project quickly.
                    </p>
                  </div>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
                  className="hidden"
                  onChange={handleImageFileChange}
                />
              </div>
            </div>
          </div>
        )}

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
                  disabled={hydrating}
                  className={cn(
                    "size-8 p-1.5 rounded-lg transition-all focus:outline-none focus:ring-2 focus:ring-primary/20",
                    color === colorOption.value
                      ? "bg-muted ring-2 ring-foreground/20"
                      : "hover:bg-muted/50"
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
