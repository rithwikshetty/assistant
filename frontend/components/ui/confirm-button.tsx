
import * as React from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import type { VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { SpinnerGap } from "@phosphor-icons/react";

type ButtonProps = React.ComponentProps<typeof Button>;

type ConfirmButtonProps = {
  onConfirm: () => Promise<void> | void;
  confirmLabel?: string;
  cancelLabel?: string;
  className?: string;
  confirmClassName?: string;
  disabled?: boolean;
  timeoutMs?: number;
  children: React.ReactNode; // idle label/content
  variant?: VariantProps<typeof buttonVariants>["variant"];
  size?: VariantProps<typeof buttonVariants>["size"];
  confirmVariant?: VariantProps<typeof buttonVariants>["variant"];
  confirmSize?: VariantProps<typeof buttonVariants>["size"];
} & Pick<ButtonProps, "aria-label" | "title">;

export function ConfirmButton({
  onConfirm,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  className,
  confirmClassName,
  disabled,
  timeoutMs = 6000,
  children,
  variant = "ghost",
  size = "sm",
  confirmVariant = "destructive",
  confirmSize = "sm",
  ...rest
}: ConfirmButtonProps) {
  const [stage, setStage] = React.useState<"idle" | "confirm" | "loading">("idle");
  const timerRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (stage === "confirm" && timeoutMs > 0) {
      timerRef.current = window.setTimeout(() => setStage("idle"), timeoutMs);
    }
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [stage, timeoutMs]);

  const handlePrimaryClick = async () => {
    if (stage === "idle") {
      setStage("confirm");
      return;
    }
    if (stage === "confirm") {
      setStage("loading");
      try {
        await onConfirm();
      } finally {
        setStage("idle");
      }
    }
  };

  if (stage === "confirm") {
    return (
      <div className={cn("inline-flex items-center gap-2", className)}>
        <Button
          type="button"
          variant={confirmVariant}
          size={confirmSize}
          className={confirmClassName}
          onClick={handlePrimaryClick}
          disabled={disabled}
          {...rest}
        >
          {confirmLabel}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size={confirmSize}
          onClick={() => setStage("idle")}
          disabled={disabled}
        >
          {cancelLabel}
        </Button>
      </div>
    );
  }

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={className}
      onClick={handlePrimaryClick}
      disabled={disabled || stage === "loading"}
      {...rest}
    >
      {stage === "loading" ? <SpinnerGap className="size-4 animate-spin" /> : children}
    </Button>
  );
}
