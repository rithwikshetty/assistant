
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

type PopoverSurfaceProps = React.ComponentPropsWithoutRef<"div"> & {
  asChild?: boolean;
  elevation?: "md" | "lg";
};

/**
 * PopoverSurface
 *
 * Small utility to standardize overlay surfaces (dropdowns, selects, popovers).
 * Applies rounded corners, border, and elevation. Use `asChild` to merge onto
 * a Radix Content element while keeping its own animation/positioning classes.
 */
export const PopoverSurface = React.forwardRef<HTMLDivElement, PopoverSurfaceProps>(
  ({ asChild = true, className, elevation = "md", ...props }, ref) => {
    const Comp = asChild ? Slot : "div";
    return (
      <Comp
        ref={ref}
        data-slot="popover-surface"
        className={cn(
          "bg-popover text-popover-foreground rounded-xl border",
          elevation === "lg" ? "shadow-lg" : "shadow-md",
          className
        )}
        {...props}
      />
    );
  }
);

PopoverSurface.displayName = "PopoverSurface";

