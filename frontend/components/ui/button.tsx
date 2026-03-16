import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg type-size-14 font-medium transition-all duration-200 ease-[cubic-bezier(0.34,1.56,0.64,1)] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 hover:shadow-md hover:-translate-y-px active:scale-[0.96] active:shadow-sm active:translate-y-0",
        destructive:
          "bg-destructive text-white shadow-sm hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 hover:shadow-md active:scale-[0.97]",
        outline:
          "border border-border bg-transparent shadow-sm hover:bg-muted/50 hover:border-border/80 dark:hover:bg-muted/30 active:scale-[0.97]",
        secondary:
          "bg-muted text-foreground shadow-sm hover:bg-muted/70 active:scale-[0.97]",
        ghost:
          "hover:bg-muted/50 hover:text-foreground active:bg-muted/70",
        link: "text-primary underline-offset-4 hover:underline",
        "filled-tonal":
          "bg-primary/10 hover:bg-primary/15 text-primary dark:bg-[color:var(--primary-surface)] dark:hover:bg-[color:var(--primary-surface-strong)] dark:text-[color:var(--primary-surface-foreground)] rounded-lg shadow-sm font-medium active:scale-[0.97]",
        "text-md3":
          "hover:bg-muted/50 text-foreground font-medium",
        "outlined-md3":
          "border border-border hover:bg-muted/50 hover:border-muted-foreground/20 text-muted-foreground hover:text-foreground rounded-lg active:scale-[0.97]",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 px-6 has-[>svg]:px-4",
        md3: "h-12 px-6 py-3",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
