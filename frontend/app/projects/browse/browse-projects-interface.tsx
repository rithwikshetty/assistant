
import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useIsMobile } from "@/hooks/use-mobile";
import { Button } from "@/components/ui/button";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  browsePublicProjects,
  joinPublicProject,
  leavePublicProject,
  type BrowseProjectsResponse,
  type PublicProjectItem,
  type ProjectOwnerSummary,
} from "@/lib/api/projects";
import { type Project } from "@/lib/api/projects-core";
import { useProjects } from "@/hooks/use-projects";
import { markdownComponents } from "@/components/markdown/markdown-components";
import { cn } from "@/lib/utils";
import { DEFAULT_PROJECT_IMAGE_SRC } from "@/lib/projects/constants";
import { CaretRight, MagnifyingGlass, X, Users, ArrowSquareOut } from "@phosphor-icons/react";

const UNCATEGORIZED_KEY = "__uncategorized";
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

function mergeProjectPatch(current: PublicProjectItem, patch: Partial<Project>): PublicProjectItem {
  const next: PublicProjectItem = { ...current };
  if ("name" in patch && patch.name !== undefined) next.name = patch.name;
  if ("description" in patch) next.description = patch.description ?? null;
  if ("category" in patch) next.category = (patch.category ?? null) as PublicProjectItem["category"];
  if ("owner_id" in patch) next.owner_id = typeof patch.owner_id === "string" ? patch.owner_id : null;
  if ("owner_name" in patch) next.owner_name = typeof patch.owner_name === "string" ? patch.owner_name : null;
  if ("owner_email" in patch) next.owner_email = typeof patch.owner_email === "string" ? patch.owner_email : null;
  if ("owners" in patch) {
    if (Array.isArray(patch.owners)) {
      next.owners = patch.owners
        .map((owner): ProjectOwnerSummary | null => {
          if (!owner) return null;
          const id = typeof owner.id === "string" ? owner.id : "";
          if (!id) return null;
          return { id, name: owner.name ?? null, email: owner.email ?? null };
        })
        .filter((owner): owner is ProjectOwnerSummary => Boolean(owner));
    } else if (patch.owners === null) {
      next.owners = [];
    }
  }
  if ("is_public" in patch && patch.is_public !== undefined) next.is_public = Boolean(patch.is_public);
  if ("is_public_candidate" in patch && patch.is_public_candidate !== undefined) next.is_public_candidate = Boolean(patch.is_public_candidate);
  if ("current_user_role" in patch && patch.current_user_role !== undefined) next.current_user_role = patch.current_user_role as PublicProjectItem["current_user_role"];

  const updatedAt = "public_image_updated_at" in patch ? patch.public_image_updated_at ?? null : next.public_image_updated_at ?? null;
  const baseImage = "public_image_url" in patch ? patch.public_image_url ?? null : next.public_image_url ?? null;
  next.public_image_updated_at = updatedAt;
  next.public_image_url = withCacheBuster(baseImage, updatedAt);
  return next;
}

type CategoryOption = {
  key: string;
  label: string;
  count: number;
};

export function BrowseProjectsInterface() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { addToast } = useToast();
  const { refreshProjects } = useProjects();

  const transformProjectList = React.useCallback((items?: PublicProjectItem[]) => {
    if (!items) return [];
    return items.map((project) => ({
      ...project,
      public_image_url: withCacheBuster(project.public_image_url ?? null, project.public_image_updated_at ?? null),
    }));
  }, []);

  const [categoryFilter, setCategoryFilter] = React.useState<string>("all");
  const [searchTerm, setSearchTerm] = React.useState<string>("");
  const [pendingMap, setPendingMap] = React.useState<Record<string, "join" | "leave">>({});
  const [expandedProjectId, setExpandedProjectId] = React.useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, error, isLoading, refetch } = useQuery<BrowseProjectsResponse>({
    queryKey: ["projects", "browse"],
    queryFn: () => browsePublicProjects(),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const projects = React.useMemo<PublicProjectItem[]>(() => transformProjectList(data?.projects), [data?.projects, transformProjectList]);
  const totalProjects = projects.length;
  const joinedCount = React.useMemo(() => projects.filter((g) => g.is_member).length, [projects]);

  const categoryOptions = React.useMemo<CategoryOption[]>(() => {
    const map = new Map<string, CategoryOption>();
    projects.forEach((project) => {
      const raw = (project.category ?? "").trim();
      const key = raw ? raw.toLowerCase() : UNCATEGORIZED_KEY;
      const label = raw || "Uncategorized";
      if (map.has(key)) {
        map.get(key)!.count += 1;
      } else {
        map.set(key, { key, label, count: 1 });
      }
    });
    return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [projects]);

  const selectedCategoryLabel = React.useMemo(() => {
    if (categoryFilter === "all" || categoryFilter === UNCATEGORIZED_KEY) return null;
    return categoryOptions.find((o) => o.key === categoryFilter)?.label ?? null;
  }, [categoryFilter, categoryOptions]);

  const useServerFiltering = Boolean(selectedCategoryLabel);
  const { data: serverFiltered, isLoading: isServerFiltering } = useQuery<BrowseProjectsResponse>({
    queryKey: ["projects", "browse", selectedCategoryLabel],
    queryFn: () => browsePublicProjects(selectedCategoryLabel!),
    enabled: useServerFiltering,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const serverFilteredProjects = React.useMemo<PublicProjectItem[]>(() => transformProjectList(serverFiltered?.projects), [
    serverFiltered?.projects,
    transformProjectList,
  ]);

  const categoryFilteredProjects = React.useMemo(() => {
    if (useServerFiltering) return serverFilteredProjects;
    if (categoryFilter === "all") return projects;
    return projects.filter((project) => {
      const key = (project.category ?? "").trim().toLowerCase() || UNCATEGORIZED_KEY;
      return key === categoryFilter;
    });
  }, [useServerFiltering, serverFilteredProjects, categoryFilter, projects]);

  const trimmedSearchTerm = React.useMemo(() => searchTerm.trim(), [searchTerm]);
  const normalizedSearchTerm = React.useMemo(() => trimmedSearchTerm.toLowerCase(), [trimmedSearchTerm]);
  const hasSearch = normalizedSearchTerm.length > 0;

  const visibleProjects = React.useMemo(() => {
    if (!hasSearch) return categoryFilteredProjects;
    return categoryFilteredProjects.filter((project) => {
      const composite = `${project.name ?? ""} ${project.description ?? ""}`.toLowerCase();
      return composite.includes(normalizedSearchTerm);
    });
  }, [categoryFilteredProjects, hasSearch, normalizedSearchTerm]);

  React.useEffect(() => {
    if (!expandedProjectId) return;
    if (!visibleProjects.some((project) => project.id === expandedProjectId)) {
      setExpandedProjectId(null);
    }
  }, [expandedProjectId, visibleProjects]);

  const setPending = React.useCallback((id: string, action?: "join" | "leave") => {
    setPendingMap((prev) => {
      const next = { ...prev };
      if (!action) delete next[id];
      else next[id] = action;
      return next;
    });
  }, []);

  const updateProjectState = React.useCallback(
    (projectId: string, updater: (project: PublicProjectItem) => PublicProjectItem) => {
      queryClient.setQueryData<BrowseProjectsResponse>(["projects", "browse"], (current) => {
        if (!current) return current;
        return {
          projects: current.projects.map((g) => (g.id === projectId ? updater(g) : g)),
        };
      });
    },
    [queryClient]
  );

  const handleJoin = React.useCallback(
    async (project: PublicProjectItem) => {
      setPending(project.id, "join");
      try {
        await joinPublicProject(project.id);
        updateProjectState(project.id, (g) => ({
          ...g,
          is_member: true,
          member_count: g.is_member ? g.member_count : g.member_count + 1,
        }));
        addToast({ type: "success", title: "Joined project", description: project.name });
        try { await refreshProjects(); } catch { }
      } catch (err) {
        addToast({ type: "error", title: "Failed to join", description: (err as Error)?.message ?? "Something went wrong" });
      } finally {
        setPending(project.id);
      }
    },
    [addToast, refreshProjects, setPending, updateProjectState]
  );

  const handleLeave = React.useCallback(
    async (project: PublicProjectItem) => {
      setPending(project.id, "leave");
      try {
        await leavePublicProject(project.id);
        updateProjectState(project.id, (g) => ({
          ...g,
          is_member: false,
          member_count: g.member_count > 0 ? g.member_count - 1 : 0,
        }));
        addToast({ type: "info", title: "Left project", description: project.name });
        try { await refreshProjects(); } catch { }
      } catch (err) {
        addToast({ type: "error", title: "Failed to leave", description: (err as Error)?.message ?? "Something went wrong" });
      } finally {
        setPending(project.id);
      }
    },
    [addToast, refreshProjects, setPending, updateProjectState]
  );

  const handleOpenProject = React.useCallback((projectId: string) => {
    navigate(`/projects/${projectId}`);
  }, [navigate]);

  const handleToggleProject = React.useCallback((projectId: string) => {
    setExpandedProjectId((prev) => (prev === projectId ? null : projectId));
  }, []);

  const handleProjectUpdated = React.useCallback(
    (event: Event) => {
      const detail = (event as CustomEvent<{ project?: Project }>).detail;
      const updatedProject = detail?.project;
      if (!updatedProject?.id) return;

      if (updatedProject.is_public === false) {
        queryClient.setQueryData<BrowseProjectsResponse>(["projects", "browse"], (current) => {
          if (!current) return current;
          return {
            projects: current.projects.filter((g) => g.id !== updatedProject.id),
          };
        });
        setExpandedProjectId((prev) => (prev === updatedProject.id ? null : prev));
        return;
      }

      const exists = projects.some((project) => project.id === updatedProject.id);
      if (!exists) {
        void refetch();
        return;
      }

      updateProjectState(updatedProject.id, (project) => mergeProjectPatch(project, updatedProject));
    },
    [projects, queryClient, refetch, updateProjectState]
  );

  React.useEffect(() => {
    window.addEventListener("frontend:projectUpdated", handleProjectUpdated as EventListener);
    return () => window.removeEventListener("frontend:projectUpdated", handleProjectUpdated as EventListener);
  }, [handleProjectUpdated]);

  const closeBrowse = React.useCallback(() => {
    try {
      if (typeof window !== "undefined" && window.history.length > 1) {
        navigate(-1);
        return;
      }
    } catch { }
    navigate("/");
  }, [navigate]);

  const showLoadingSkeleton = (isLoading || (useServerFiltering && isServerFiltering)) && categoryFilteredProjects.length === 0;
  const showEmptyState = !isLoading && !isServerFiltering && visibleProjects.length === 0;
  const hasCategoryFilters = categoryOptions.length > 0;

  const content = (
    <>
        {/* Header Section */}
        <header className="flex-none border-b border-border/30 bg-background/90 backdrop-blur-xl z-20 hidden">
          {/* Hidden standard header */}
        </header>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto min-h-0 relative">
          {/* Mobile Sidebar Trigger - Absolute */}
          {isMobile && (
            <div className="absolute top-6 left-4 z-50">
              <SidebarTrigger />
            </div>
          )}

          {/* Close Button - Absolute Top Right */}
          <div className="absolute top-6 right-6 z-50">
            <Button
              variant="ghost"
              size="icon"
              onClick={closeBrowse}
              className="rounded-lg hover:bg-muted/50"
            >
              <X className="h-5 w-5 opacity-70" />
            </Button>
          </div>

          {/* Immersive Hero Background */}
          <div className="absolute top-0 left-0 right-0 h-[320px] z-0 overflow-hidden pointer-events-none">
            <img
              src="/bg.png"
              alt="Abstract architectural ribbon"
              className="absolute inset-0 h-full w-full object-cover opacity-40 dark:opacity-20"
              style={{ objectPosition: "center 45%" }}
            />
            <div className="absolute inset-0 bg-gradient-to-b from-background/0 via-background/60 to-background" />
          </div>

          <div className="relative z-10 mx-auto w-full max-w-7xl px-4 sm:px-8 pt-20 pb-20">
            {/* Hero Content */}
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 mb-12">
              <div className="max-w-xl space-y-3">
                <h2 className="type-hero-title">
                  Discover shared project workspaces.
                </h2>
                <p className="type-hero-subtitle text-muted-foreground/90 max-w-lg">
                  Browse knowledge spaces that teams have opened to the whole organisation, complete with shared context, curated resources, and updates.
                </p>
              </div>

              <div className="flex items-center gap-8 md:gap-12 pb-1">
                <div className="flex flex-col">
                  <span className="type-overline">Available</span>
                  <span className="type-hero-title">{totalProjects}</span>
                </div>
                <div className="flex flex-col">
                  <span className="type-overline">Joined</span>
                  <span className="type-hero-title">{joinedCount}</span>
                </div>
              </div>
            </div>

            {/* Search and Filter Bar */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center mb-8">
              <SearchInput
                value={searchTerm}
                onChange={setSearchTerm}
                placeholder="Search projects..."
                containerClassName="flex-1 max-w-md"
                className="h-10"
              />

              {hasCategoryFilters && (
                <div className="overflow-x-auto scrollbar-hide -mx-4 px-4 sm:mx-0 sm:px-0">
                  <div className="flex items-center gap-1 p-1 rounded-xl bg-muted/20 border border-border/5 w-fit">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setCategoryFilter("all")}
                      className={cn(
                        "px-4 py-1.5 rounded-lg transition-all duration-200 whitespace-nowrap h-auto type-control",
                        categoryFilter === "all"
                          ? "bg-background shadow-sm text-foreground ring-1 ring-black/5 dark:ring-white/10"
                          : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                      )}
                    >
                      All
                    </Button>
                    {categoryOptions.map((option) => (
                      <Button
                        key={option.key}
                        variant="ghost"
                        size="sm"
                        onClick={() => setCategoryFilter(option.key)}
                        className={cn(
                          "px-4 py-1.5 rounded-lg transition-all duration-200 whitespace-nowrap h-auto type-control",
                          categoryFilter === option.key
                            ? "bg-background shadow-sm text-foreground ring-1 ring-black/5 dark:ring-white/10"
                            : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                        )}
                      >
                        {option.label}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {error && (
              <div className="mb-6 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 type-body text-destructive">
                Failed to load projects. <Button variant="link" onClick={() => refetch()} className="underline font-medium p-0 h-auto">Retry</Button>
              </div>
            )}

            {showLoadingSkeleton ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-4 p-4 rounded-xl border border-border/40">
                    <Skeleton className="h-10 w-10 rounded-lg" />
                    <div className="space-y-2 flex-1">
                      <Skeleton className="h-4 w-1/3" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            {!isLoading && showEmptyState ? (
              <EmptyState
                hasFilter={categoryFilter !== "all"}
                hasSearch={hasSearch}
                searchTerm={trimmedSearchTerm}
                onResetFilters={() => setCategoryFilter("all")}
                onClearSearch={() => setSearchTerm("")}
              />
            ) : null}

            {!showEmptyState && visibleProjects.length > 0 && (
              <div className="flex flex-col pb-20">
                {visibleProjects.map((project) => (
                  <ProjectRow
                    key={project.id}
                    project={project}
                    expanded={expandedProjectId === project.id}
                    pendingAction={pendingMap[project.id]}
                    onToggle={handleToggleProject}
                    onJoin={handleJoin}
                    onLeave={handleLeave}
                    onOpen={handleOpenProject}
                  />
                ))}
              </div>
            )}
          </div>
        </main>
    </>
  );

  return <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-background">{content}</div>;
}

type ProjectRowProps = {
  project: PublicProjectItem;
  expanded: boolean;
  pendingAction?: "join" | "leave";
  onToggle: (projectId: string) => void;
  onJoin: (project: PublicProjectItem) => Promise<void> | void;
  onLeave: (project: PublicProjectItem) => Promise<void> | void;
  onOpen: (projectId: string) => void;
};

function ProjectRow({
  project,
  expanded,
  pendingAction,
  onToggle,
  onJoin,
  onLeave,
  onOpen,
}: ProjectRowProps) {
  const joined = project.is_member;
  const description = (project.description ?? "").trim() || "No description available.";
  const isJoining = pendingAction === "join";
  const isLeaving = pendingAction === "leave";

  const heroSrc = project.public_image_url ?? DEFAULT_PROJECT_IMAGE_SRC;

  return (
    <div
      className={cn(
        "group relative border-b border-border/40 last:border-0 transition-all duration-300",
        expanded ? "bg-muted/20" : "hover:bg-muted/10"
      )}
    >
      <div
        onClick={() => onToggle(project.id)}
        className="flex items-center gap-4 p-4 cursor-pointer select-none"
      >
        <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-md border border-border/20 bg-muted">
          <img
            src={heroSrc}
            alt={project.name}
            className="absolute inset-0 h-full w-full object-cover"
          />
        </div>

        <div className="flex-1 min-w-0 flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <h3 className={cn("type-control truncate", expanded ? "text-primary" : "text-foreground")}>
              {project.name}
            </h3>
            {joined && (
              <span className="inline-flex items-center rounded-lg bg-primary/10 px-1.5 py-0.5 type-nav-meta text-primary">
                Joined
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 type-caption">
            <span className="flex items-center gap-1">
              <Users className="h-3 w-3" />
              {project.member_count}
            </span>
            {project.category && (
              <>
                <span className="h-0.5 w-0.5 rounded-full bg-muted-foreground/50" />
                <span className="truncate max-w-[150px]">{project.category}</span>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-8 w-8 text-muted-foreground transition-transform duration-300", expanded && "rotate-90")}
          >
            <CaretRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-300 ease-in-out",
          expanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="overflow-hidden">
          <div className="px-4 pb-6 pt-0 pl-[4.5rem]">
            <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none type-body-muted text-muted-foreground/90">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {description}
              </ReactMarkdown>
            </div>

            <div className="mt-6 flex items-center gap-3">
              {joined ? (
                <>
                  <Button
                    onClick={() => onOpen(project.id)}
                    className="h-9 px-4 type-control-compact shadow-sm"
                  >
                    <ArrowSquareOut className="mr-2 h-3.5 w-3.5" />
                    Open Project
                  </Button>
                  <ConfirmButton
                    variant="ghost"
                    confirmVariant="destructive"
                    disabled={isLeaving}
                    confirmLabel="Confirm Leave"
                    onConfirm={() => void onLeave(project)}
                    className="h-9 px-4 type-control-compact text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  >
                    {isLeaving ? "Leaving..." : "Leave Project"}
                  </ConfirmButton>
                </>
              ) : (
                <Button
                  onClick={() => void onJoin(project)}
                  disabled={isJoining}
                  className="h-9 px-6 type-control-compact shadow-sm"
                >
                  {isJoining ? "Joining..." : "Join Project"}
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type EmptyStateProps = {
  hasFilter: boolean;
  hasSearch: boolean;
  searchTerm: string;
  onResetFilters: () => void;
  onClearSearch: () => void;
};

function EmptyState({ hasFilter, hasSearch, searchTerm, onResetFilters, onClearSearch }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="h-12 w-12 rounded-xl bg-muted/50 flex items-center justify-center mb-4">
        <MagnifyingGlass className="h-5 w-5 text-muted-foreground" />
      </div>
      <h3 className="type-body font-medium text-foreground">No projects found</h3>
      <p className="mt-1 type-caption max-w-xs mx-auto">
        {hasSearch
          ? `We couldn't find anything matching "${searchTerm}"`
          : "Try adjusting your filters or search terms."}
      </p>
      <div className="mt-4 flex gap-2">
        {hasSearch && (
          <Button variant="outline" size="sm" onClick={onClearSearch} className="h-8 type-control-compact">
            Clear Search
          </Button>
        )}
        {hasFilter && (
          <Button variant="ghost" size="sm" onClick={onResetFilters} className="h-8 type-control-compact">
            Reset Filters
          </Button>
        )}
      </div>
    </div>
  );
}
