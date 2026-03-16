
import { useState, useEffect, useRef, KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

interface InlineTitleEditorProps {
  initialTitle: string;
  comparisonTitle?: string;
  isEditing: boolean;
  onSave: (newTitle: string) => void;
  onCancel: () => void;
  className?: string;
  disabled?: boolean;
}

export function InlineTitleEditor({
  initialTitle,
  comparisonTitle,
  isEditing,
  onSave,
  onCancel,
  className,
  disabled = false,
}: InlineTitleEditorProps) {
  const [title, setTitle] = useState(initialTitle);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset title when initialTitle changes or editing starts
  useEffect(() => {
    setTitle(initialTitle);
  }, [initialTitle, isEditing]);

  // Focus and select text when editing starts
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSave = () => {
    const trimmedTitle = title.trim();
    const baselineTitle = (comparisonTitle ?? initialTitle).trim();
    if (trimmedTitle && trimmedTitle !== baselineTitle) {
      onSave(trimmedTitle);
    } else {
      onCancel();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setTitle(initialTitle);
      onCancel();
    }
  };

  const handleBlur = () => {
    // Small delay to allow button clicks to register
    setTimeout(() => {
      handleSave();
    }, 100);
  };

  if (!isEditing) {
    return (
      <span className={cn("type-nav-row text-sidebar-foreground truncate", className)}>
        {initialTitle}
      </span>
    );
  }

  return (
    <input
      ref={inputRef}
      type="text"
      value={title}
      onChange={(e) => setTitle(e.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
      disabled={disabled}
      className={cn(
        "type-nav-row text-sidebar-foreground bg-transparent border border-accent-yellow/60 rounded px-2 py-1 outline-none focus:border-accent-yellow w-full min-w-0",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
      maxLength={100}
    />
  );
}
