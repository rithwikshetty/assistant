
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FolderSimple, SpinnerGap } from "@phosphor-icons/react";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { createProject } from "@/lib/api/projects-core";
import { useProjects } from "@/hooks/use-projects";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

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

interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
}

export function CreateProjectDialog({ open, onClose }: CreateProjectDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [customInstructions, setCustomInstructions] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const { addToast } = useToast();
  const navigate = useNavigate();
  const { updateProjects } = useProjects();

  const trimmedName = name.trim();
  const nameLength = trimmedName.length;
  const overNameLimit = nameLength > MAX_NAME_LENGTH;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!trimmedName) {
      addToast({ type: "error", title: "Name required", description: "Please enter a project name" });
      return;
    }

    if (nameLength > MAX_NAME_LENGTH) {
      addToast({
        type: "error",
        title: "Project name too long",
        description: `Keep project names to ${MAX_NAME_LENGTH} characters or fewer.`,
      });
      return;
    }

    setCreating(true);

    try {
      const project = await createProject({
        name: trimmedName,
        description: description.trim() || undefined,
        custom_instructions: customInstructions.trim() || undefined,
        color: color || undefined,
      });

      // Add the new project to the cache; preserve existing order
      updateProjects((current) => [{ ...project, conversation_count: 0 }, ...current]);

      addToast({ type: "success", title: "Project created", description: `"${project.name}" has been created` });

      // Close dialog and reset form
      onClose();
      setName("");
      setDescription("");
      setCustomInstructions("");
      setColor(null);

      // Navigate to project
      navigate(`/projects/${project.id}`);
    } catch (error) {
      addToast({
        type: "error",
        title: "Failed to create project",
        description: error instanceof Error ? error.message : "An error occurred",
      });
    } finally {
      setCreating(false);
    }
  };

  const handleClose = () => {
    if (!creating) {
      onClose();
      // Reset form after close animation
      setTimeout(() => {
        setName("");
        setDescription("");
        setCustomInstructions("");
        setColor(null);
      }, 150);
    }
  };

  return (
    <Modal open={open} onClose={handleClose} title="Create New Project">
      <form onSubmit={handleSubmit} className="space-y-4">
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
            disabled={creating}
            autoFocus
          />
          <div className="mt-1 flex items-center justify-between type-size-12">
            <span className={cn(
              "transition-colors",
              overNameLimit ? "text-destructive" : "text-muted-foreground"
            )}>
              {overNameLimit
                ? `Project names are limited to ${MAX_NAME_LENGTH} characters.`
                : `Up to ${MAX_NAME_LENGTH} characters.`}
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
            disabled={creating}
            rows={6}
            className="resize-y min-h-[160px]"
            maxLength={5000}
          />
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
            disabled={creating}
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
                disabled={creating}
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

        <div className="flex justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={handleClose}
            disabled={creating}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={creating || !trimmedName || overNameLimit}
          >
            {creating ? (
              <span className="inline-flex items-center gap-1.5">
                <SpinnerGap className="size-4 animate-spin" aria-hidden />
                Creating project…
              </span>
            ) : "Create project"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
