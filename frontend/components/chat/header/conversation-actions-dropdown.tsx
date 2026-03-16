import { SpinnerGap, ShareNetwork, GitBranch, DotsThree } from "@phosphor-icons/react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

type ConversationActionsDropdownProps = {
  onShare: () => void;
  onBranch: () => void;
  isSharing: boolean;
  isBranching: boolean;
  isHydrated: boolean;
  viewerIsOwner: boolean;
};

export const ConversationActionsDropdown = ({
  onShare,
  onBranch,
  isSharing,
  isBranching,
  isHydrated,
  viewerIsOwner,
}: ConversationActionsDropdownProps) => {
  const isBusy = isSharing || isBranching;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="inline-flex items-center justify-center rounded-lg p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Conversation actions"
        >
          {isBusy ? (
            <SpinnerGap className="h-5 w-5 animate-spin" />
          ) : (
            <DotsThree className="h-5 w-5" />
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8}>
        <DropdownMenuItem
          onClick={onShare}
          disabled={!isHydrated || !viewerIsOwner || isSharing}
        >
          {isSharing ? (
            <SpinnerGap className="h-4 w-4 animate-spin" />
          ) : (
            <ShareNetwork className="h-4 w-4" />
          )}
          {isSharing ? "Sharing" : "Share conversation"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onBranch} disabled={isBranching}>
          {isBranching ? (
            <SpinnerGap className="h-4 w-4 animate-spin" />
          ) : (
            <GitBranch className="h-4 w-4" />
          )}
          {isBranching ? "Branching" : "Branch from last message"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
