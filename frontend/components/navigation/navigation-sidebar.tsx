import * as React from "react"
import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { useLocation, useNavigate } from "react-router-dom"
import { MagnifyingGlass, List, Globe, SquaresFour, ListChecks, X } from "@phosphor-icons/react"
import { motion, AnimatePresence } from "framer-motion"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar"
import { ErrorBoundary } from "@/components/error-boundary"
import { useToast } from "@/components/ui/toast"
import { TooltipIconButton } from "@/components/tools/tooltip-icon-button"
import { useAuth } from "@/contexts/auth-context"
import { getUnseenAssignedTaskCount } from "@/lib/api/tasks"
import { ThreadListNew, ThreadListContent } from "./thread-list"
import { UserProfileDropdown } from "./user-profile-dropdown"
import { cn } from "@/lib/utils"
import { getEnv } from "@/lib/utils/env"

const SIDEBAR_SCROLL_STORAGE_KEY = "assist:navigation-sidebar:scrollTop"
const SIDEBAR_LANE_INSET_CLASS = "px-2"
const SIDEBAR_PRIMARY_SECTION_CLASS = cn("flex py-1.5", SIDEBAR_LANE_INSET_CLASS)
const SIDEBAR_FOOTER_CLASS = cn("border-t border-sidebar-border/30 pt-2 pb-3", SIDEBAR_LANE_INSET_CLASS)

export function NavigationSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const { state, toggleSidebar } = useSidebar();
  const isCollapsed = state === "collapsed";
  const scrollContainerRef = React.useRef<HTMLDivElement | null>(null);
  const location = useLocation();
  const pathname = location.pathname;

  useEffect(() => {
    const node = scrollContainerRef.current;
    if (!node) return;

    const handleScroll = () => {
      try {
        sessionStorage.setItem(SIDEBAR_SCROLL_STORAGE_KEY, String(node.scrollTop));
      } catch {
        // Ignore storage errors
      }
    };

    node.addEventListener("scroll", handleScroll, { passive: true });
    return () => node.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const node = scrollContainerRef.current;
    if (!node) return;

    const frame = requestAnimationFrame(() => {
      try {
        const stored = sessionStorage.getItem(SIDEBAR_SCROLL_STORAGE_KEY);
        if (stored) {
          const value = Number(stored);
          if (Number.isFinite(value)) {
            node.scrollTop = value;
          }
        }
      } catch {
        // Ignore storage errors
      }
    });

    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  const handleSearchClick = () => {
    setIsSearchOpen(!isSearchOpen);
  };

  const closeSearch = () => {
    setIsSearchOpen(false);
    setSearchQuery("");
  };

  useEffect(() => {
    if (isCollapsed) {
      setIsSearchOpen(false);
    }
  }, [isCollapsed]);

  return (
    <Sidebar {...props}>
      <SidebarHeader>
        <div className="flex h-12 items-center justify-between">
          <TooltipIconButton
            tooltip="Toggle sidebar"
            side={isCollapsed ? "right" : "bottom"}
            sizeClass="compact"
            onClick={toggleSidebar}
            className="rounded-lg transition-colors duration-200 ease-md-standard hover:bg-sidebar-accent"
          >
            <List className="size-4 text-muted-foreground hover:text-foreground transition-colors duration-200" />
          </TooltipIconButton>

          {!isCollapsed && (
            <div className="flex items-center gap-1.5">
              <AnimatePresence mode="wait" initial={false}>
                {isSearchOpen ? (
                  <motion.div
                    key="search-input"
                    initial={{ width: 0, opacity: 0 }}
                    animate={{ width: "auto", opacity: 1 }}
                    exit={{ width: 0, opacity: 0 }}
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                    className="flex items-center gap-1.5 overflow-hidden"
                  >
                    <div className="relative">
                      <input
                        type="text"
                        placeholder="Search..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="h-7 w-36 rounded-md border border-border/50 bg-muted/30 px-2.5 pr-7 type-control-compact outline-none transition-all duration-200 focus:w-44 focus:bg-background focus:border-primary/30 focus:ring-1 focus:ring-primary/20"
                        autoFocus
                        onBlur={() => {
                          setTimeout(() => {
                            closeSearch();
                          }, 150);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            closeSearch();
                          }
                        }}
                      />
                      {searchQuery && (
                        <button
                          type="button"
                          onClick={closeSearch}
                          className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        >
                          <X className="size-3" />
                        </button>
                      )}
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key="search-button"
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.8, opacity: 0 }}
                    transition={{ type: "spring", stiffness: 400, damping: 25 }}
                  >
                    <TooltipIconButton
                      tooltip="Search chats"
                      side="bottom"
                      sizeClass="compact"
                      onClick={handleSearchClick}
                      className="rounded-lg transition-colors duration-200 ease-md-standard hover:bg-sidebar-accent"
                    >
                      <MagnifyingGlass className="size-4 text-muted-foreground hover:text-foreground transition-colors duration-200" />
                    </TooltipIconButton>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </SidebarHeader>

      <SidebarMenu className={cn(SIDEBAR_PRIMARY_SECTION_CLASS, "stagger-children")}>
        <ThreadListNew />
        <SecondaryActionsRow />
      </SidebarMenu>

      <SidebarContent ref={scrollContainerRef}>
        <div
          className={cn(
            "h-full transition-opacity duration-200 ease-md-standard",
            isCollapsed ? "pointer-events-none opacity-0" : "opacity-100"
          )}
        >
          <ErrorBoundary>
            <ThreadListContent searchQuery={searchQuery} />
          </ErrorBoundary>
        </div>
      </SidebarContent>

      <SidebarRail />
      <SidebarFooter className={SIDEBAR_FOOTER_CLASS}>
        <UserProfileDropdown />
      </SidebarFooter>
    </Sidebar>
  )
}

function SecondaryActionsRow() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const { addToast } = useToast();
  const isProjectsEnabled = getEnv("VITE_ENABLE_PROJECTS", "true") === "true";
  const isPowerUser = (user?.user_tier || "").toLowerCase() === "power";
  const isProjectsActive =
    location.pathname === "/projects/browse" ||
    location.pathname.startsWith("/projects/browse/");
  const isSkillsActive = location.pathname.startsWith("/skills");
  const isTasksActive = location.pathname.startsWith("/tasks");
  const { data: unseenCount = 0 } = useQuery<number>({
    queryKey: ["tasks-unseen-count"],
    queryFn: getUnseenAssignedTaskCount,
    staleTime: 20_000,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (!user?.id || unseenCount <= 0) return;
    const key = `assist:tasks-unseen-toast:${user.id}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch {
      // Ignore storage failures and continue with a best-effort toast.
    }
    addToast({
      title: "New assigned tasks",
      description: `You have ${unseenCount} new assigned ${unseenCount === 1 ? "task" : "tasks"}.`,
      type: "info",
    });
  }, [user?.id, unseenCount, addToast]);

  return (
    <>
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip={isProjectsEnabled ? "Projects" : "Projects (testing)"}
          onClick={() => isProjectsEnabled && navigate("/projects/browse")}
          isActive={isProjectsActive}
          disabled={!isProjectsEnabled}
          className={cn(
            "h-8 !rounded-lg text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent group-data-[collapsible=icon]:rounded-lg",
            isProjectsActive && "text-sidebar-primary font-medium bg-sidebar-primary/10",
            !isProjectsEnabled && "opacity-40 cursor-not-allowed"
          )}
          aria-label={isProjectsEnabled ? "Projects" : "Projects (testing)"}
        >
          <Globe className="size-4" />
          <span>Projects</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
      {isPowerUser && (
        <SidebarMenuItem>
          <SidebarMenuButton
            tooltip="Skills"
            onClick={() => navigate("/skills")}
            isActive={isSkillsActive}
            className={cn(
              "h-8 !rounded-lg text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent group-data-[collapsible=icon]:rounded-lg",
              isSkillsActive && "text-sidebar-primary font-medium bg-sidebar-primary/10",
            )}
            aria-label="Skills"
          >
            <SquaresFour className="size-4" />
            <span>Skills</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      )}
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="Tasks"
          onClick={() => navigate("/tasks")}
          isActive={isTasksActive}
          className={cn(
            "h-8 !rounded-lg text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent group-data-[collapsible=icon]:rounded-lg",
            isTasksActive && "text-sidebar-primary font-medium bg-sidebar-primary/10",
          )}
          aria-label="Tasks"
        >
          <ListChecks className="size-4" />
          <span>Tasks</span>
          {unseenCount > 0 && (
            <span className="ml-auto flex h-[18px] min-w-[18px] items-center justify-center rounded-md bg-sidebar-primary/15 px-1 py-0.5 type-size-10 font-semibold leading-none tabular-nums text-sidebar-primary group-data-[collapsible=icon]:hidden">
              {unseenCount > 99 ? "99+" : unseenCount}
            </span>
          )}
        </SidebarMenuButton>
      </SidebarMenuItem>
    </>
  );
}
