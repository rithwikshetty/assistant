
import * as React from "react";
import { MagnifyingGlass, X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

export interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange"> {
  value: string;
  onChange: (value: string) => void;
  /** Show clear button when there's a value */
  clearable?: boolean;
  /** Container className */
  containerClassName?: string;
}

export function SearchInput({
  value,
  onChange,
  clearable = true,
  placeholder = "Search...",
  className,
  containerClassName,
  ...props
}: SearchInputProps) {
  const showClear = clearable && value.length > 0;

  return (
    <div className={cn("relative group", containerClassName)}>
      <MagnifyingGlass
        className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground/70 group-hover:text-foreground transition-colors pointer-events-none"
        aria-hidden="true"
      />
      <Input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(
          "pl-9 pr-3 rounded-lg bg-muted/20 border-border/5 hover:bg-muted/30 transition-colors focus-visible:ring-1 focus-visible:ring-primary/20 shadow-none",
          showClear && "pr-8",
          className
        )}
        {...props}
      />
      {showClear && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          aria-label="Clear search"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}

export default SearchInput;
