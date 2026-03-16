import { Suspense, lazy, type ReactNode } from "react";
import { Outlet, Route, Routes, useParams } from "react-router-dom";
import { Providers } from "@/app/providers";
import { useAuth } from "@/contexts/auth-context";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { NavigationSidebar } from "@/components/navigation/navigation-sidebar";
import { ChatInterface } from "@/app/chat-interface";

// Lazy-load route-level pages
const BrowseProjectsInterface = lazy(() =>
  import("@/app/projects/browse/browse-projects-interface").then((m) => ({ default: m.BrowseProjectsInterface })),
);
const TasksInterface = lazy(() =>
  import("@/app/tasks/tasks-interface").then((m) => ({ default: m.TasksInterface })),
);
const PowerUserGuard = lazy(() =>
  import("@/components/auth/power-user-guard").then((module) => ({ default: module.PowerUserGuard })),
);
const SkillsInterface = lazy(() =>
  import("@/app/skills/skills-interface").then((module) => ({ default: module.SkillsInterface })),
);
const ShareImportPage = lazy(() => import("@/app/share/[token]/share-import-page"));
const ProjectShareJoinPage = lazy(() => import("@/app/share/project/[token]/project-share-join-page"));
const NotFound = lazy(() => import("@/app/not-found"));

function AuthLoadingSkeleton() {
  // Read sidebar cookie to match the actual layout structure
  const sidebarOpen = document.cookie
    .split(";")
    .map((c) => c.trim())
    .some((c) => c === "sidebar_state=true") ||
    !document.cookie.includes("sidebar_state=");

  const sidebarWidth = sidebarOpen ? "19rem" : "3.5rem";

  return (
    <div className="flex min-h-dvh w-full">
      {/* Sidebar placeholder */}
      <div
        className="hidden md:block shrink-0 bg-sidebar/80 border-r border-sidebar-border/50"
        style={{ width: sidebarWidth }}
      />
      {/* Content area */}
      <div className="flex flex-1 items-center justify-center">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-primary" />
      </div>
    </div>
  );
}

function AppReadyRoute() {
  const { isLoading, isBackendAuthenticated } = useAuth();

  if (isLoading) {
    return <AuthLoadingSkeleton />;
  }

  if (!isBackendAuthenticated) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background p-6">
        <div className="max-w-md text-center">
          <h1 className="type-section-title">assistant</h1>
          <p className="type-body-muted mt-3">
            The local workspace user could not be loaded. Check backend connectivity and try again.
          </p>
        </div>
      </div>
    );
  }

  return <Outlet />;
}

function AppShellRoutes() {
  return (
    <Routes>
      <Route element={<AppReadyRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<PersonalChatRoute />}>
            <Route index element={null} />
            <Route path="chat/:id" element={null} />
          </Route>
          <Route path="/projects/:projectId" element={<ProjectRoute />} />
          <Route path="/projects/:projectId/chat/:conversationId" element={<ProjectChatRoute />} />
          <Route path="/projects/browse" element={<BrowseProjectsInterface />} />
          <Route
            path="/skills"
            element={
              <PowerUserGuard>
                <SkillsInterface />
              </PowerUserGuard>
            }
          />
          <Route path="/tasks" element={<TasksInterface />} />
          <Route path="/share/:token" element={<ShareImportPage />} />
          <Route path="/share/project/:token" element={<ProjectShareJoinPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Suspense fallback={null}><NotFound /></Suspense>} />
    </Routes>
  );
}

function PageSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-primary" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function AppLayout() {
  return (
    <SidebarProvider className="flex h-dvh w-full overflow-hidden">
      <NavigationSidebar collapsible="icon" />
      <SidebarInset className="relative min-h-0 overflow-hidden">
        <PageSuspense>
          <Outlet />
        </PageSuspense>
      </SidebarInset>
    </SidebarProvider>
  );
}

function PersonalChatRoute() {
  const { id } = useParams<{ id?: string }>();
  return <ChatInterface conversationId={id} />;
}

function ProjectRoute() {
  const { projectId } = useParams<{ projectId: string }>();
  return <ChatInterface projectId={projectId} />;
}

function ProjectChatRoute() {
  const { projectId, conversationId } = useParams<{ projectId: string; conversationId: string }>();
  return <ChatInterface projectId={projectId} conversationId={conversationId} />;
}

export function AppRouter() {
  return (
    <Providers>
      <AppShellRoutes />
    </Providers>
  );
}
