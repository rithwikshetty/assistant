import { useMemo } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type ProjectMember } from "@/lib/api/project-sharing";
import { getInitials } from "./utils";

const MAX_VISIBLE = 4;

type ProjectMemberAvatarsProps = {
  /** All sorted project members. */
  allMembers: ProjectMember[];
  /** Fallback owner shown when isPublic=true and no owner members are found. */
  primaryOwner?: ProjectMember | null;
  isLoading: boolean;
  /** When true, only show owner-role members instead of the full member list. */
  isPublic: boolean;
  maxVisible?: number;
};

export const ProjectMemberAvatars = ({
  allMembers,
  primaryOwner,
  isLoading,
  isPublic,
  maxVisible = MAX_VISIBLE,
}: ProjectMemberAvatarsProps) => {
  const ownerMembers = useMemo(
    () => allMembers.filter((m) => m.role === "owner"),
    [allMembers],
  );

  const displayMembers = isPublic ? ownerMembers : allMembers;
  const visibleMembers = displayMembers.slice(0, maxVisible);
  const remaining = Math.max(displayMembers.length - visibleMembers.length, 0);

  return (
    <div className="hidden sm:flex items-center pl-1.5 pr-2 py-0.5">
      {isLoading ? (
        Array.from({ length: isPublic ? Math.min(ownerMembers.length || 1, maxVisible) || 1 : 3 }).map(
          (_, index) => (
            <span
              key={`avatar-skeleton-${index}`}
              className="h-7 w-7 sm:h-8 sm:w-8 animate-pulse rounded-full bg-muted ring-2 ring-background"
              style={{
                marginLeft: index === 0 ? "0" : "-0.4rem",
                zIndex: maxVisible - index,
              }}
            />
          ),
        )
      ) : displayMembers.length > 0 ? (
        <>
          {visibleMembers.map((member, index) => {
            const label = member.user_name || member.user_email || "Owner";
            const roleLabel = member.role === "owner" ? "Owner" : "Member";
            const tooltipText = isPublic ? `${label} (Owner)` : `${label} (${roleLabel})`;
            return (
              <Tooltip key={`${isPublic ? "owner" : "member"}-${member.user_id}`}>
                <TooltipTrigger asChild>
                  <Avatar
                    className="h-7 w-7 sm:h-8 sm:w-8 ring-2 ring-background transition-transform hover:scale-110 hover:z-50"
                    style={{
                      marginLeft: index === 0 ? "0" : "-0.4rem",
                      zIndex: visibleMembers.length - index,
                    }}
                  >
                    <AvatarFallback className="bg-primary/10 text-primary dark:bg-[color:var(--primary-surface)] dark:text-[color:var(--primary-surface-foreground)] type-control-compact leading-none px-0.5">
                      {getInitials(label)}
                    </AvatarFallback>
                  </Avatar>
                </TooltipTrigger>
                <TooltipContent side="bottom" align="center">
                  {tooltipText}
                </TooltipContent>
              </Tooltip>
            );
          })}
          {remaining > 0 ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className="flex h-7 w-7 sm:h-8 sm:w-8 items-center justify-center rounded-full bg-muted type-nav-meta font-semibold text-muted-foreground ring-2 ring-background transition-transform hover:scale-110 hover:z-50"
                  style={{ marginLeft: "-0.4rem", zIndex: 0 }}
                >
                  +{remaining}
                </span>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="center">
                {remaining} {isPublic ? `other owner${remaining > 1 ? "s" : ""}` : `more member${remaining > 1 ? "s" : ""}`}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </>
      ) : isPublic && primaryOwner ? (
        /* Public project fallback: show primaryOwner when no owner-role members found */
        (() => {
          const label = primaryOwner.user_name || primaryOwner.user_email || "Owner";
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <Avatar className="h-7 w-7 sm:h-8 sm:w-8 ring-2 ring-background">
                  <AvatarFallback className="bg-primary/10 text-primary type-control-compact leading-none px-0.5">
                    {getInitials(label)}
                  </AvatarFallback>
                </Avatar>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="center">{label} (Owner)</TooltipContent>
            </Tooltip>
          );
        })()
      ) : null}
    </div>
  );
};
