
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { importSharedConversation } from "@/lib/api/share";
import { useAuth } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";

export default function ShareImportPage() {
  const params = useParams();
  const navigate = useNavigate();
  const { isBackendAuthenticated } = useAuth();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);

  const token = Array.isArray(params.token) ? params.token[0] : params.token;

  useEffect(() => {
    if (!isBackendAuthenticated) {
      // Wait for auth to complete
      return;
    }

    if (!token) {
      setStatus("error");
      setMessage("Invalid share link");
      return;
    }

    const importConversation = async () => {
      try {
        const response = await importSharedConversation(token);
        setStatus("success");
        setMessage(response.message);
        setConversationId(response.conversation_id);

        // Auto-redirect after 2 seconds
        setTimeout(() => {
          navigate(`/chat/${response.conversation_id}`);
        }, 2000);
      } catch (error) {
        // Import failed
        setStatus("error");
        if (error instanceof Error) {
          if (error.message.includes("expired")) {
            setMessage("This share link has expired (7 days)");
          } else if (error.message.includes("not found")) {
            setMessage("Invalid or deleted share link");
          } else {
            setMessage(error.message);
          }
        } else {
          setMessage("Failed to import conversation. Please try again.");
        }
      }
    };

    void importConversation();
  }, [token, isBackendAuthenticated, navigate]);

  return (
    <div className="flex min-h-svh w-full items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md space-y-6 rounded-lg border border-border bg-card p-8 shadow-lg">
        {status === "loading" && (
          <>
            <div className="flex justify-center">
              <div className="h-12 w-12 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            </div>
            <h1 className="type-section-title text-center">
              Importing conversation...
            </h1>
            <p className="type-body-muted text-center">
              Please wait while we add this to your conversations
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <div className="flex justify-center">
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
            </div>
            <h1 className="type-section-title text-center">
              Success!
            </h1>
            <p className="type-body-muted text-center">
              {message}
            </p>
            <p className="type-caption text-muted-foreground text-center">
              Redirecting to the conversation...
            </p>
            {conversationId && (
              <Button onClick={() => navigate(`/chat/${conversationId}`)} className="w-full">
                Go to conversation now
              </Button>
            )}
          </>
        )}

        {status === "error" && (
          <>
            <div className="flex justify-center">
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
            </div>
            <h1 className="type-section-title text-center">
              Import failed
            </h1>
            <p className="type-body-muted text-center">
              {message}
            </p>
            <Button onClick={() => navigate("/")} variant="secondary" className="w-full">
              Go home
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
