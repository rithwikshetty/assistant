import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowsClockwise, Plus, SpinnerGap, X } from "@phosphor-icons/react";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { useIsMobile } from "@/hooks/use-mobile";
import { SearchInput } from "@/components/ui/search-input";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import {
  createCustomSkill,
  disableCustomSkill,
  enableCustomSkill,
  getCustomSkills,
  getSkillsManifest,
  type SkillManifestItem,
} from "@/lib/api/skills";
import { SkillCard } from "@/components/skills/skill-card";
import { SkillDetailModal } from "@/components/skills/skill-detail-modal";
import { SkillEditorModal } from "@/components/skills/skill-editor-modal";

export function SkillsInterface() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const isMobile = useIsMobile();

  const [search, setSearch] = React.useState("");
  const [selectedSkill, setSelectedSkill] = React.useState<SkillManifestItem | null>(null);
  const [editingSkillId, setEditingSkillId] = React.useState<string | null>(null);
  const [isCreatingSkill, setIsCreatingSkill] = React.useState(false);
  const [togglingSkillIds, setTogglingSkillIds] = React.useState<Set<string>>(new Set());

  const {
    data: manifest,
    isLoading: isManifestLoading,
    error: manifestError,
    refetch: refetchManifest,
  } = useQuery({
    queryKey: ["skills", "manifest"],
    queryFn: getSkillsManifest,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const {
    data: customSkillsResponse,
    isLoading: isCustomSkillsLoading,
    error: customSkillsError,
    refetch: refetchCustomSkills,
  } = useQuery({
    queryKey: ["skills", "custom"],
    queryFn: getCustomSkills,
    staleTime: 30 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const normalizedSearch = React.useMemo(() => search.trim().toLowerCase(), [search]);

  const globalSkills = React.useMemo(() => {
    const skills = manifest?.skills || [];
    return skills.filter((skill) => {
      if (skill.source !== "global") return false;

      if (!normalizedSearch) return true;
      const searchable = `${skill.id} ${skill.title} ${skill.description} ${skill.when_to_use}`.toLowerCase();
      return searchable.includes(normalizedSearch);
    });
  }, [manifest?.skills, normalizedSearch]);

  const customSkills = React.useMemo(() => {
    const skills = customSkillsResponse?.skills || [];
    return skills.filter((skill) => {
      if (!normalizedSearch) return true;
      const searchable = `${skill.id} ${skill.title} ${skill.description} ${skill.when_to_use} ${skill.status}`.toLowerCase();
      return searchable.includes(normalizedSearch);
    });
  }, [customSkillsResponse?.skills, normalizedSearch]);

  const hasError = Boolean(manifestError || customSkillsError);
  const isCatalogLoading =
    (isManifestLoading && !manifest) ||
    (isCustomSkillsLoading && !customSkillsResponse);

  const handleCreateCustomSkill = React.useCallback(async () => {
    try {
      setIsCreatingSkill(true);
      const created = await createCustomSkill();
      queryClient.setQueryData(["skills", "custom", "detail", created.id], created);
      await queryClient.invalidateQueries({ queryKey: ["skills", "custom"] });
      setEditingSkillId(created.id);
      addToast({ type: "success", title: "Custom skill created", description: "You can start editing now." });
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: "Couldn't create custom skill", description });
    } finally {
      setIsCreatingSkill(false);
    }
  }, [addToast, queryClient]);

  const handleToggleSkill = React.useCallback(async (skillId: string, enable: boolean) => {
    setTogglingSkillIds((prev) => new Set(prev).add(skillId));
    try {
      const updated = enable
        ? await enableCustomSkill(skillId)
        : await disableCustomSkill(skillId);
      queryClient.setQueryData(["skills", "custom", "detail", skillId], updated);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills", "custom"] }),
        queryClient.invalidateQueries({ queryKey: ["skills", "manifest"] }),
      ]);
      addToast({
        type: "success",
        title: enable ? "Skill enabled" : "Skill disabled",
      });
    } catch (err) {
      const description = err instanceof Error ? err.message : "Please try again.";
      addToast({ type: "error", title: enable ? "Failed to enable" : "Failed to disable", description });
    } finally {
      setTogglingSkillIds((prev) => {
        const next = new Set(prev);
        next.delete(skillId);
        return next;
      });
    }
  }, [addToast, queryClient]);

  const handleRefresh = React.useCallback(() => {
    void refetchManifest();
    void refetchCustomSkills();
  }, [refetchCustomSkills, refetchManifest]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-2 px-4 sm:px-8 bg-background/90 backdrop-blur-md border-b border-border/30">
        <div className="flex items-center gap-3">
          {isMobile && <SidebarTrigger className="-ml-2" />}
          <div className="flex flex-col">
            <h1 className="type-page-title">Skills</h1>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => {
            try {
              if (typeof window !== "undefined" && window.history.length > 1) {
                navigate(-1);
              } else {
                navigate("/");
              }
            } catch {
              navigate("/");
            }
          }}
          aria-label="Close skills"
          className="rounded-lg hover:bg-foreground/5 text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-5 w-5" />
        </Button>
      </header>

      <main className="flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-8 sm:py-12 flex flex-col gap-6">
          <div className="flex items-center gap-3">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search skills..."
              containerClassName="w-full max-w-md"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={handleRefresh}
              className="shrink-0 text-muted-foreground hover:text-foreground"
            >
              <ArrowsClockwise className="size-4" />
            </Button>
          </div>

          {isCatalogLoading && (
            <div className="flex items-center justify-center py-20">
              <p className="type-size-14 text-muted-foreground animate-pulse">Loading skills...</p>
            </div>
          )}

          {hasError && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-5">
              <p className="type-size-14 font-medium text-destructive">Failed to load skills.</p>
              <p className="mt-1 type-size-12 text-destructive/70">
                Refresh the page. If this keeps happening, check backend connectivity.
              </p>
            </div>
          )}

          {!isCatalogLoading && !hasError && globalSkills.length === 0 && customSkills.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center gap-3">
              <p className="type-size-14 text-muted-foreground">
                {search ? "No skills match your search." : "No skills available."}
              </p>
              {!search && (
                <Button type="button" onClick={() => void handleCreateCustomSkill()} disabled={isCreatingSkill}>
                  {isCreatingSkill ? <SpinnerGap className="size-4 animate-spin" /> : <Plus className="size-4" />}
                  Create Custom Skill
                </Button>
              )}
            </div>
          )}

          {!isCatalogLoading && !hasError && (globalSkills.length > 0 || customSkills.length > 0) && (
            <div className="flex flex-col gap-10">
              {globalSkills.length > 0 && (
                <section>
                  <h2 className="type-size-14 font-medium text-foreground/80 mb-4">Pre-installed</h2>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {globalSkills.map((skill, index) => (
                      <SkillCard
                        key={`${skill.source}:${skill.id}`}
                        skill={skill}
                        index={index}
                        onClick={() => setSelectedSkill(skill)}
                      />
                    ))}
                  </div>
                </section>
              )}

              <section>
                <div className="mb-4 flex items-center justify-between gap-3">
                  <h2 className="type-size-14 font-medium text-foreground/80">Custom</h2>
                  <Button type="button" variant="outline" size="sm" onClick={() => void handleCreateCustomSkill()} disabled={isCreatingSkill}>
                    {isCreatingSkill ? <SpinnerGap className="size-4 animate-spin" /> : <Plus className="size-4" />}
                    Create Custom Skill
                  </Button>
                </div>

                {customSkills.length > 0 ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {customSkills.map((skill, index) => (
                      <SkillCard
                        key={`custom:${skill.id}`}
                        skill={skill}
                        index={index}
                        showToggle
                        isToggling={togglingSkillIds.has(skill.id)}
                        onToggle={(checked) => void handleToggleSkill(skill.id, checked)}
                        onClick={() => setEditingSkillId(skill.id)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center gap-4 rounded-2xl border border-dashed border-border/50 px-5 py-4 transition-colors duration-200 ease-out">
                    <div className="shrink-0 size-11 rounded-xl bg-muted/20 flex items-center justify-center">
                      <Plus className="size-5 text-muted-foreground/40" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="type-control text-muted-foreground/60">No custom skills yet</p>
                      <p className="type-caption text-muted-foreground/40 mt-0.5">
                        Create one to draft and enable your own workflow.
                      </p>
                    </div>
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      </main>

      <SkillDetailModal skill={selectedSkill} onClose={() => setSelectedSkill(null)} />

      <SkillEditorModal
        skillId={editingSkillId}
        onClose={() => setEditingSkillId(null)}
        onDeleted={() => setEditingSkillId(null)}
      />
    </div>
  );
}
