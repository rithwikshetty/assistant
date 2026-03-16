
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { useProjects } from "@/hooks/use-projects";
import { joinProjectViaShareLink } from "@/lib/api/project-sharing";

type JoinStatus = "idle" | "auth-wait" | "loading" | "success" | "error";

interface JoinState {
  status: JoinStatus;
  message: string;
  projectId: string | null;
  projectName: string | null;
}

export default function ProjectShareJoinPage() {
  const params = useParams();
  const navigate = useNavigate();
  const { isBackendAuthenticated } = useAuth();
  const { refreshProjects } = useProjects();
  const [state, setState] = useState<JoinState>({
    status: "idle",
    message: "",
    projectId: null,
    projectName: null,
  });

  const token = useMemo(() => {
    const raw = Array.isArray(params.token) ? params.token[0] : params.token;
    return typeof raw === "string" && raw.trim().length > 0 ? raw.trim() : null;
  }, [params.token]);

  useEffect(() => {
    if (!token) {
      setState({ status: "error", message: "Invalid project invite link", projectId: null, projectName: null });
      return;
    }

    if (!isBackendAuthenticated) {
      setState((prev) => ({ ...prev, status: "auth-wait" }));
      return;
    }

    let isActive = true;

    const attemptJoin = async () => {
      setState({ status: "loading", message: "Joining project...", projectId: null, projectName: null });
      try {
        const response = await joinProjectViaShareLink(token);
        if (!isActive) return;

        setState({
          status: "success",
          message: response.message,
          projectId: response.project_id,
          projectName: response.project_name,
        });

        try {
          await refreshProjects();
        } catch (_) {
          // ignore refresh failures
        }

        setTimeout(() => {
          navigate(`/projects/${response.project_id}`);
        }, 2000);
      } catch (error) {
        if (!isActive) return;

        const message = error instanceof Error ? error.message : "Unable to join project.";
        const lowered = message.toLowerCase();
        let displayMessage = message;
        if (lowered.includes("expired")) {
          displayMessage = "This invite link has expired.";
        } else if (lowered.includes("not found")) {
          displayMessage = "This invite link is invalid or has been revoked.";
        }

        setState({ status: "error", message: displayMessage, projectId: null, projectName: null });
      }
    };

    void attemptJoin();

    return () => {
      isActive = false;
    };
  }, [token, isBackendAuthenticated, refreshProjects, navigate]);

  const heading = useMemo(() => {
    switch (state.status) {
      case "success":
        return state.projectName ? `Joined ${state.projectName}` : "Joined project";
      case "error":
        return "Join failed";
      case "auth-wait":
      case "loading":
      case "idle":
      default:
        return "Joining project";
    }
  }, [state.projectName, state.status]);

  const description = useMemo(() => {
    switch (state.status) {
      case "success":
        return state.message || "You now have access to this project.";
      case "error":
        return state.message || "We couldn't add you to this project.";
      case "auth-wait":
        return "Please finish signing in so we can accept the invite.";
      case "loading":
        return "Please wait while we confirm your invite.";
      case "idle":
      default:
        return "Checking your project invite.";
    }
  }, [state.message, state.status]);

  return (
    <div className="flex min-h-svh w-full items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md space-y-6 rounded-lg border border-border bg-card p-8 shadow-lg">
        {(state.status === "loading" || state.status === "auth-wait" || state.status === "idle") && (
          <div className="flex flex-col items-center gap-6">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            <div className="space-y-2 text-center">
              <h1 className="type-section-title">{heading}</h1>
              <p className="type-body-muted">{description}</p>
            </div>
          </div>
        )}

        {state.status === "success" && (
          <div className="flex flex-col items-center gap-6">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100 dark:bg-green-900">
              <svg
                className="h-6 w-6 text-green-600 dark:text-green-300"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div className="space-y-2 text-center">
              <h1 className="type-section-title">{heading}</h1>
              <p className="type-body-muted">{description}</p>
              <p className="type-caption text-muted-foreground">Redirecting to the project...</p>
            </div>
            {state.projectId && (
              <Button onClick={() => navigate(`/projects/${state.projectId}`)} className="w-full">
                Open project now
              </Button>
            )}
          </div>
        )}

        {state.status === "error" && (
          <div className="flex flex-col items-center gap-6">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100 dark:bg-red-900">
              <svg
                className="h-6 w-6 text-red-600 dark:text-red-300"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <div className="space-y-2 text-center">
              <h1 className="type-section-title">{heading}</h1>
              <p className="type-body-muted">{description}</p>
            </div>
            <Button onClick={() => navigate("/")} variant="secondary" className="w-full">
              Go home
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
