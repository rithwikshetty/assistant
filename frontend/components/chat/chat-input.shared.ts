import { Paperclip } from "@phosphor-icons/react";
import type { Icon as IconComponent } from "@phosphor-icons/react";
import type { StagedFileUploadResponse } from "@/lib/api/staged-files";

export type Attachment = {
  id: string;
  uploadId: string;
  file: File;
  name: string;
  size: number;
  status: "uploading" | "processing" | "ready" | "error";
  backendId?: string;
  meta?: StagedFileUploadResponse;
  errorMessage?: string;
};

export type AttachmentMeta = {
  id: string;
  name: string;
  contentType?: string;
  fileSize?: number;
};

export type ReadyAttachment = Attachment & {
  status: "ready";
  backendId: string;
};

export type SlashCommand = {
  id: string;
  label: string;
  icon: IconComponent;
};

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    id: "attach",
    label: "Add photos & files",
    icon: Paperclip,
  },
];

export function isReadyAttachment(
  attachment: Attachment
): attachment is ReadyAttachment {
  return (
    attachment.status === "ready" &&
    typeof attachment.backendId === "string" &&
    attachment.backendId.trim().length > 0
  );
}

export function toAttachmentMeta(attachment: ReadyAttachment): AttachmentMeta {
  return {
    id: attachment.backendId,
    name: attachment.meta?.original_filename || attachment.name,
    contentType: attachment.file.type || undefined,
    fileSize: attachment.size,
  };
}
