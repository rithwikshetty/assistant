import { useMemo } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type ProjectMember } from "@/lib/api/project-sharing";
import { getInitials } from "./utils";

const MAX_VISIBLE = 4;

type ProjectMemberAvatarsProps = {
  allMembers: ProjectMember[];
  isLoading: boolean;
  maxVisible?: number;
};

export const ProjectMemberAvatars = ({
  allMembers,
  isLoading,
  maxVisible = MAX_VISIBLE,
}: ProjectMemberAvatarsProps) => {
  const displayMembers = useMemo(() => allMembers, [allMembers]);
  const visibleMembers = displayMembers.slice(0, maxVisible);
  const remaining = Math.max(displayMembers.length - visibleMembers.length, 0);

  return (
    <div className="hidden sm:flex items-center pl-1.5 pr-2 py-0.5">
      {isLoading ? (
        Array.from({ length: 3 }).map(
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
            return (
              <Tooltip key={`member-${member.user_id}`}>
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
                  {`${label} (${roleLabel})`}
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
                {remaining} {`more member${remaining > 1 ? "s" : ""}`}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </>
      ) : null}
    </div>
  );
};
