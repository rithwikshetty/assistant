
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Copy, Shield, Users } from "@phosphor-icons/react";
import {
  generateProjectShareLink,
  leaveProject,
  updateProjectMemberRole,
  type ProjectShareResponse,
  type ProjectMemberRole,
} from "@/lib/api/project-sharing";
import { tryWebShare, tryClipboardWrite } from "@/lib/share-helpers";
import { useProjectMembersContext } from "@/contexts/project-members-context";
import { parseBackendDate } from "@/lib/datetime";
import { getProject, type Project } from "@/lib/api/projects-core";
import { updateProjectVisibility } from "@/lib/api/projects";
import { ConfirmButton } from "@/components/ui/confirm-button";
import { useProjects } from "@/hooks/use-projects";

interface ProjectSharingDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  projectName?: string | null;
}

export function ProjectSharingDialog({ open, onClose, projectId, projectName }: ProjectSharingDialogProps) {
  const { addToast } = useToast();
  const navigate = useNavigate();
  const { updateProjects } = useProjects();
  const membersContext = useProjectMembersContext();
  const [project, setProject] = useState<Project | null>(null);
  const [visibilityPending, setVisibilityPending] = useState(false);
  const [shareInfo, setShareInfo] = useState<ProjectShareResponse | null>(null);
  const [generatingLink, setGeneratingLink] = useState(false);
  const [updatingMemberId, setUpdatingMemberId] = useState<string | null>(null);
  const [leaveInProgress, setLeaveInProgress] = useState(false);
  // Custom instructions are no longer editable in this dialog to avoid duplication

  useEffect(() => {
    if (!open) {
      setShareInfo(null);
      setGeneratingLink(false);
      setUpdatingMemberId(null);
      setLeaveInProgress(false);
      setProject(null);
      setVisibilityPending(false);
      // no-op for instructions; edit-only in Edit Project details dialog
    }
  }, [open]);

  const members = membersContext?.members ?? null;
  const isLoadingMembers = Boolean(membersContext?.isLoading);
  const isOwner = Boolean(membersContext?.isOwner);
  const currentMember = membersContext?.currentUserMember ?? null;
  const ownersList = membersContext?.owners ?? [];
  const ownerCount = membersContext?.ownerCount ?? ownersList.length;
  const memberCount = members ? members.length : 0;
  const hasMultipleOwners = ownerCount > 1;
  const isSoloOwner = isOwner && ownerCount <= 1 && memberCount <= 1 && !isLoadingMembers;
  const ownerBlockedFromLeaving = isOwner && !hasMultipleOwners && memberCount > 1;

  const sortedMembers = useMemo(() => {
    const list = members ?? [];
    return [...list].sort((a, b) => {
      if (a.role === "owner" && b.role !== "owner") return -1;
      if (b.role === "owner" && a.role !== "owner") return 1;
      const nameA = (a.user_name || a.user_email || "").toLocaleLowerCase();
      const nameB = (b.user_name || b.user_email || "").toLocaleLowerCase();
      return nameA.localeCompare(nameB);
    });
  }, [members]);

  // Load minimal project info to enable public toggle (instructions view handled elsewhere)
  useEffect(() => {
    (async () => {
      if (!open) return;
      try {
        const fetchedProject = await getProject(projectId);
        setProject(fetchedProject);
      } catch {
        // non-blocking for sharing/members
      }
    })();
  }, [open, projectId]);

  const handleRoleChange = useCallback(
    async (memberId: string, nextRole: ProjectMemberRole) => {
      setUpdatingMemberId(memberId);
      try {
        await updateProjectMemberRole(projectId, memberId, nextRole);
        await membersContext?.refetch?.();
        addToast({ type: "success", title: nextRole === "owner" ? "Owner added" : "Owner removed" });
      } catch (error) {
        addToast({
          type: "error",
          title: "Role update failed",
          description: error instanceof Error ? error.message : "Please try again.",
        });
      } finally {
        setUpdatingMemberId((current) => (current === memberId ? null : current));
      }
    },
    [addToast, membersContext, projectId],
  );

  const handleCopyShareLink = async () => {
    setGeneratingLink(true);
    try {
      const response = await generateProjectShareLink(projectId);
      // Always reveal the link UI so there is a manual fallback
      setShareInfo(response);

      // Prefer native share sheet on mobile
      const shared = await tryWebShare({
        url: response.share_url,
        title: projectName ? `Join ${projectName} on assistant` : "Join this assistant project",
        text: "Use this link to join the project (expires in 7 days).",
      });
      if (shared) {
        addToast({ type: "success", title: "Share sheet opened" });
        return;
      }

      // Fallback to clipboard
      const copied = await tryClipboardWrite(response.share_url);
      if (copied) {
        addToast({
          type: "success",
          title: "Project link copied",
          description: "Share it with teammates to invite them for the next 7 days.",
        });
        return;
      }

      // Final fallback: link is visible in the dialog for manual copy
      addToast({ type: "info", title: "Link ready — tap Copy in the box" });
    } catch (error) {
      addToast({
        type: "error",
        title: "Couldn't generate link",
        description: error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      setGeneratingLink(false);
    }
  };

  const handleLeaveProject = async () => {
    setLeaveInProgress(true);
    try {
      const result = await leaveProject(projectId);
      const successMessage = result?.message || (isOwner ? "Project deleted" : "Left project");
      addToast({ type: "success", title: successMessage });
      updateProjects((current) => current.filter((projectItem) => projectItem.id !== projectId));
      onClose();
      navigate("/");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Please try again.";
      const normalized = message.trim();
      const ownerNeedsBackup = Boolean(
        ownerBlockedFromLeaving && normalized.toLowerCase().includes("add another owner"),
      );
      addToast({
        type: "error",
        title: ownerNeedsBackup ? "Add another owner" : "Couldn't leave project",
        description: ownerNeedsBackup
          ? "Promote another member to owner before leaving."
          : normalized || "Please try again.",
      });
    } finally {
      setLeaveInProgress(false);
    }
  };

  // Instructions editing removed here; use Edit Project dialog instead

  const expiresLabel = useMemo(() => {
    if (!shareInfo?.expires_at) return null;
    try {
      const date = parseBackendDate(shareInfo.expires_at);
      if (!date) return null;
      return new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }).format(date);
    } catch {
      return null;
    }
  }, [shareInfo?.expires_at]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={projectName ? `Manage "${projectName}"` : "Manage project"}
      className="sm:max-w-lg"
    >
      <div className="space-y-6">
        <section className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="type-size-14 font-semibold text-foreground flex items-center gap-2">
                <Users className="size-4" />
                Invite teammates
              </h4>
              <p className="type-size-14 text-muted-foreground">
                Generate a link to invite colleagues. Links remain active for 7 days.
              </p>
            </div>
            <Button size="sm" variant="secondary" onClick={handleCopyShareLink} disabled={generatingLink}>
              {generatingLink ? "Generating..." : "Copy link"}
            </Button>
          </div>
          {shareInfo ? (
            <div className="rounded-xl border border-border/60 bg-muted/10 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <Input value={shareInfo.share_url} readOnly className="type-size-12" onFocus={(e) => e.currentTarget.select()} />
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  className="shrink-0"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(shareInfo.share_url);
                      addToast({ type: "success", title: "Link copied" });
                    } catch (_error) {
                      addToast({ type: "error", title: "Copy failed" });
                    }
                  }}
                >
                  <Copy className="size-4" />
                </Button>
              </div>
              <p className="type-size-12 text-muted-foreground">Expires {expiresLabel ?? "in 7 days"}</p>
            </div>
          ) : null}
        </section>

        {Boolean(project?.is_public_candidate && isOwner) ? (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <Users className="size-4 text-muted-foreground" />
              <h4 className="type-size-14 font-semibold text-foreground">Project Visibility</h4>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-border/60 bg-muted/5 px-4 py-3">
              <div className="flex flex-col">
                <span className="type-size-14 text-foreground">{project?.is_public ? 'Public' : 'Private (not listed)'}</span>
                <span className="type-size-12 text-muted-foreground">
                  {project?.is_public
                    ? 'Anyone in your org can find and join.'
                    : 'Only members can access. You can publish later.'}
                </span>
              </div>
              <div>
                <ConfirmButton
                  aria-label={project?.is_public ? 'Make project private' : 'Publish project'}
                  variant={project?.is_public ? 'secondary' : 'ghost'}
                  confirmVariant={project?.is_public ? 'destructive' : 'default'}
                  disabled={visibilityPending}
                  confirmLabel={project?.is_public ? 'Confirm unpublish' : 'Confirm publish'}
                  onConfirm={async () => {
                    if (!project) return;
                    const next = !project.is_public;
                    setVisibilityPending(true);
                    try {
                      await updateProjectVisibility(project.id, next);
                      setProject({ ...project, is_public: next });
                      try {
                        updateProjects((current) =>
                          current.map((p) => (p.id === project.id ? { ...p, is_public: next } : p))
                        );
                      } catch {}
                      addToast({ type: 'success', title: next ? 'Published' : 'Unpublished' });
                    } catch (err) {
                      addToast({ type: 'error', title: 'Update failed', description: (err as Error)?.message ?? '' });
                    } finally {
                      setVisibilityPending(false);
                    }
                  }}
                >
                  {project?.is_public ? 'Make private' : 'Publish'}
                </ConfirmButton>
              </div>
            </div>
          </section>
        ) : null}

        {/* Custom instructions editing removed from Manage dialog to keep a single edit surface. */}

        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <Shield className="size-4 text-muted-foreground" />
            <h4 className="type-size-14 font-semibold text-foreground">Members</h4>
          </div>
          <div className="rounded-xl border border-border/60 bg-muted/5">
            {isLoadingMembers ? (
              <div className="space-y-3 p-4">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div key={index} className="flex items-center gap-3">
                    <Skeleton className="size-9 rounded-full" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-3 w-32" />
                      <Skeleton className="h-3 w-24" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <ul className="divide-y divide-border/60">
                {sortedMembers.map((member) => {
                  const initials = getInitials(member.user_name || member.user_email);
                  const isCurrent = member.user_id === currentMember?.user_id;
                  const canPromote = isOwner && member.role !== "owner";
                  const canDemote = isOwner && member.role === "owner" && ownerCount > 1;
                  const updatingThisMember = updatingMemberId === member.user_id;
                  return (
                    <li key={member.user_id} className="flex items-center gap-3 px-4 py-3">
                      <Avatar className="size-9">
                        <AvatarFallback className="bg-muted type-size-14 font-medium text-foreground/90">
                          {initials}
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex-1">
                        <p className="type-size-14 font-medium text-foreground">
                          {member.user_name || member.user_email}
                        </p>
                        <p className="type-size-12 text-muted-foreground flex items-center gap-2">
                          <span className="capitalize">{member.role}</span>
                          {isCurrent ? <span className="rounded-full bg-muted px-2 py-0.5 type-size-10">You</span> : null}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        {canPromote ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="type-size-14"
                            disabled={updatingThisMember}
                            onClick={() => handleRoleChange(member.user_id, "owner")}
                          >
                            {updatingThisMember ? "Saving..." : "Make owner"}
                          </Button>
                        ) : null}
                        {canDemote ? (
                          <ConfirmButton
                            aria-label="Confirm remove owner"
                            variant="secondary"
                            size="sm"
                            confirmVariant="destructive"
                            confirmSize="sm"
                            disabled={updatingThisMember}
                            confirmLabel="Confirm"
                            onConfirm={() => handleRoleChange(member.user_id, "member")}
                          >
                            {member.user_id === currentMember?.user_id ? "Step down" : "Remove owner"}
                          </ConfirmButton>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
                {sortedMembers.length === 0 ? (
                  <li className="px-4 py-6 text-center type-size-14 text-muted-foreground">
                    No members yet. Share the project to invite collaborators.
                  </li>
                ) : null}
              </ul>
            )}
          </div>
        </section>

        <section className="space-y-4">
          <div className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 space-y-3">
            <h4 className="type-size-14 font-semibold text-destructive">
              {isOwner
                ? ownerBlockedFromLeaving
                  ? "Owner cannot leave yet"
                  : isSoloOwner
                    ? "Delete project"
                    : "Leave project"
                : "Leave project"}
            </h4>
            <p className="type-size-14 text-muted-foreground">
              {isOwner
                ? ownerBlockedFromLeaving
                ? "Promote another member to owner before leaving this project."
                : isSoloOwner
                    ? "Leaving will delete this project and all of its conversations."
                    : "Leaving will remove you as an owner. Your conversations will be archived."
                : "Leaving will delete your conversations in this project. You can rejoin later via a share link."}
            </p>
            <Button
              type="button"
              variant="destructive"
              className="w-full sm:w-auto"
              disabled={leaveInProgress || isLoadingMembers || ownerBlockedFromLeaving}
              onClick={handleLeaveProject}
            >
              {leaveInProgress
                ? isOwner && isSoloOwner
                  ? "Deleting..."
                  : "Leaving..."
                : isOwner && isSoloOwner
                  ? "Delete project"
                  : "Leave project"}
            </Button>
            {ownerBlockedFromLeaving ? (
              <p className="type-size-12 text-muted-foreground">Add another owner in the list above, then try again.</p>
            ) : null}
          </div>
        </section>
      </div>
    </Modal>
  );
}

function getInitials(value: string | undefined): string {
  if (!value) return "?";
  const trimmed = value.trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  if (trimmed.includes("@")) {
    return trimmed.slice(0, 2).toUpperCase();
  }
  return trimmed.slice(0, 2).toUpperCase();
}
