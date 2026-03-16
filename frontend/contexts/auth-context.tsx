/* @refresh skip */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getCurrentUser } from "@/lib/api/auth";

interface User {
  id: string;
  email: string;
  name: string;
  image?: string;
  role?: string;
  user_tier?: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isBackendAuthenticated: boolean;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);


export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const backendUser = await getCurrentUser();
      if (!backendUser) {
        setUser(null);
        return;
      }
      setUser({
        id: backendUser.id,
        email: backendUser.email,
        name: backendUser.name,
        role: backendUser.role,
        user_tier: backendUser.user_tier,
      });
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      setIsLoading(true);
      try {
        const backendUser = await getCurrentUser();
        if (!cancelled && backendUser) {
          setUser({
            id: backendUser.id,
            email: backendUser.email,
            name: backendUser.name,
            role: backendUser.role,
            user_tier: backendUser.user_tier,
          });
        } else if (!cancelled) {
          setUser(null);
        }
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthContextType>(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user,
      isBackendAuthenticated: !!user,
      refreshUser,
    }),
    [isLoading, refreshUser, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}


export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
