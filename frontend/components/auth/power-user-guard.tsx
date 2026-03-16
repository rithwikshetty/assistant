import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldWarning } from "@phosphor-icons/react";

import { useAuth } from "@/contexts/auth-context";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface PowerUserGuardProps {
  children: React.ReactNode;
}

export function PowerUserGuard({ children }: PowerUserGuardProps) {
  const { user, isLoading } = useAuth();
  const navigate = useNavigate();
  const isPowerUser = (user?.user_tier || "").toLowerCase() === "power";

  useEffect(() => {
    if (!isLoading && !isPowerUser) {
      const timer = setTimeout(() => {
        navigate("/");
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isLoading, isPowerUser, navigate]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary" />
      </div>
    );
  }

  if (!isPowerUser) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="max-w-md">
          <CardHeader className="text-center">
            <ShieldWarning className="mx-auto mb-4 h-12 w-12 text-destructive" />
            <CardTitle className="type-size-32">Access Denied</CardTitle>
          </CardHeader>
          <CardContent className="text-center">
            <p className="mb-4 text-muted-foreground">
              You don&apos;t have permission to access this page. Power user tier is required.
            </p>
            <p className="type-size-14 text-muted-foreground">Redirecting to home page...</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}
