/* @refresh skip */

/* @refresh skip */
import { createContext, useContext, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProjectMembers, type ProjectMember } from "@/lib/api/project-sharing";
import { useAuth } from "@/contexts/auth-context";

type ProjectMembersContextValue = {
  projectId: string | null;
  members: ProjectMember[];
  owners: ProjectMember[];
  primaryOwner: ProjectMember | null;
  ownerCount: number;
  currentUserMember: ProjectMember | null;
  isOwner: boolean;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<ProjectMember[] | undefined>;
};

const ProjectMembersContext = createContext<ProjectMembersContextValue | null>(null);

export function ProjectMembersProvider({
  projectId,
  children,
}: {
  projectId?: string | null;
  children: React.ReactNode;
}) {
  const effectiveProjectId = projectId ?? null;
  const { user } = useAuth();

  const queryKey = ["project-members", effectiveProjectId] as const;

  const { data, error, isLoading, refetch } = useQuery<ProjectMember[]>({
    queryKey,
    queryFn: () => getProjectMembers(effectiveProjectId!).then((res) => res.members),
    enabled: !!effectiveProjectId,
    staleTime: 2 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const value = useMemo<ProjectMembersContextValue>(() => {
    const members = Array.isArray(data) ? data.slice() : [];
    const owners = members.filter((member) => member.role === "owner");
    const primaryOwner = owners[0] ?? null;
    const currentUserMember = user
      ? members.find((member) => {
          if (member.user_id === user.id) return true;
          if (user.email && member.user_email) {
            return member.user_email.toLowerCase() === user.email.toLowerCase();
          }
          return false;
        }) ?? null
      : null;

    const errMessage = error instanceof Error ? error.message : error ? String(error) : null;

    return {
      projectId: effectiveProjectId,
      members,
      owners,
      primaryOwner,
      ownerCount: owners.length,
      currentUserMember,
      isOwner: !!currentUserMember && currentUserMember.role === "owner",
      isLoading: Boolean(isLoading && !data),
      error: errMessage,
      refetch: async () => {
        const result = await refetch();
        return result.data;
      },
    };
  }, [data, error, effectiveProjectId, isLoading, refetch, user]);

  if (!effectiveProjectId) {
    return <>{children}</>;
  }

  return (
    <ProjectMembersContext.Provider value={value}>
      {children}
    </ProjectMembersContext.Provider>
  );
}

export function useProjectMembersContext(): ProjectMembersContextValue | null {
  return useContext(ProjectMembersContext);
}
