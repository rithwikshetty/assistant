
import { FC, useEffect, useState } from "react";
import { Info, Shield, ShieldCheck, Paperclip } from "@phosphor-icons/react";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { getRedactionList } from "@/lib/api/redaction-list";

interface FileUploadWarningDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  /** Whether to show the redaction toggle. Defaults to false. */
  showRedactionToggle?: boolean;
  /** Current redaction state. Only used if showRedactionToggle is true. */
  redactionEnabled?: boolean;
  /** Callback when redaction toggle changes. Only used if showRedactionToggle is true. */
  onRedactionChange?: (value: boolean) => void;
  /** Optional disabled state for redaction toggle */
  redactionDisabled?: boolean;
  /** Custom title for the dialog. Defaults to "Before you upload" */
  title?: string;
  /** Custom confirm button text. Defaults to "Upload" */
  confirmText?: string;
}

/**
 * A standardized warning dialog shown before file uploads.
 * Includes security reminders and optional redaction toggle.
 */
export const FileUploadWarningDialog: FC<FileUploadWarningDialogProps> = ({
  open,
  onClose,
  onConfirm,
  showRedactionToggle = false,
  redactionEnabled = false,
  onRedactionChange,
  redactionDisabled = false,
  title = "Before you upload",
  confirmText = "Upload",
}) => {
  const canToggleRedaction = showRedactionToggle && typeof onRedactionChange === "function";
  const [entryCount, setEntryCount] = useState<number | null>(null);

  // Fetch redaction list count when dialog opens (only count enabled entries)
  useEffect(() => {
    if (open && canToggleRedaction) {
      getRedactionList()
        .then((entries) => setEntryCount(entries.filter(e => e.is_active).length))
        .catch(() => setEntryCount(null));
    }
  }, [open, canToggleRedaction]);

  const handleViewList = () => {
    onClose();
    // Emit custom event to open settings to redaction section
    window.dispatchEvent(new CustomEvent("open-settings", { detail: { section: "redaction" } }));
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="md"
    >
      <div className="space-y-5">
        {/* Info cards */}
        <div className="space-y-3">
          {/* Quick reminder + Secure storage combined */}
          <div className="p-3 rounded-lg bg-muted/40 border border-border/50 space-y-3">
            <div className="flex items-start gap-3">
              <Info className="size-5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <div>
                <p className="type-size-14 font-medium text-foreground">Quick reminder</p>
                <p className="type-size-12 text-muted-foreground mt-0.5">
                  Avoid uploading highly sensitive client information, especially where the client has requested AI not to be used.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Shield className="size-5 text-primary flex-shrink-0 mt-0.5" />
              <div>
                <p className="type-size-14 font-medium text-foreground">Secure storage</p>
                <p className="type-size-12 text-muted-foreground mt-0.5">
                  Your files are stored on the local instance running this workspace.
                </p>
              </div>
            </div>
          </div>

          {/* Redaction Toggle */}
          {canToggleRedaction && (
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/40 border border-border/50">
              <ShieldCheck className="size-5 text-primary flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3">
                  <p className="type-size-14 font-medium text-foreground">Redact sensitive information</p>
                  <Switch
                    checked={redactionEnabled}
                    onCheckedChange={(checked) => onRedactionChange?.(checked)}
                    disabled={redactionDisabled}
                  />
                </div>
                <p className="type-size-12 text-muted-foreground mt-1.5">
                  Automatically remove names, emails, and other personal data from uploaded files.
                </p>
                {typeof entryCount === "number" && (
                  <p className="type-size-12 text-muted-foreground mt-1">
                    Your redaction list:{" "}
                    <Button
                      type="button"
                      variant="link"
                      onClick={handleViewList}
                      className="h-auto p-0 type-size-12 text-primary hover:underline"
                    >
                      {entryCount} {entryCount === 1 ? "entry" : "entries"}
                    </Button>
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-end gap-2 pt-4 border-t border-border/50">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-muted-foreground"
          >
            Cancel
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={onConfirm}
            className="gap-1.5 hover:translate-y-0"
          >
            <Paperclip className="size-3.5" />
            {confirmText}
          </Button>
        </div>
      </div>
    </Modal>
  );
};
