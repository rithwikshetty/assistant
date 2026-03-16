import { CaretRight } from "@phosphor-icons/react";

import type { SkillManifestItem } from "@/lib/api/skills";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { getSkillVisual } from "./skill-utils";

export function SkillCard({
  skill,
  index,
  onClick,
  showToggle = false,
  onToggle,
  isToggling = false,
}: {
  skill: Pick<SkillManifestItem, "id" | "title" | "description" | "status" | "source">;
  index: number;
  onClick: () => void;
  showToggle?: boolean;
  onToggle?: (checked: boolean) => void;
  isToggling?: boolean;
}) {
  const { Icon, color } = getSkillVisual(skill.id);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group flex items-center gap-4 rounded-2xl border border-border/50 px-5 py-4 text-left",
        "transition-colors duration-200 ease-out",
        "hover:border-border/70 hover:bg-card/30",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
        "animate-in fade-in slide-in-from-bottom-2",
      )}
      style={{ animationDelay: `${Math.min(index * 40, 400)}ms`, animationFillMode: "backwards" }}
    >
      <div className={cn("shrink-0 size-11 rounded-xl flex items-center justify-center", color.bg)}>
        <Icon className={cn("size-5", color.text)} />
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="type-control text-foreground truncate">{skill.title}</h3>
        <p className="type-caption text-muted-foreground truncate mt-0.5">{skill.description}</p>
      </div>
      {showToggle ? (
        <Switch
          checked={skill.status === "enabled"}
          disabled={isToggling}
          onCheckedChange={(checked) => onToggle?.(checked)}
          onClick={(e) => e.stopPropagation()}
          className={cn(isToggling && "opacity-50")}
        />
      ) : (
        <CaretRight className="size-4 shrink-0 text-muted-foreground/30 transition-colors group-hover:text-muted-foreground/60" />
      )}
    </button>
  );
}
