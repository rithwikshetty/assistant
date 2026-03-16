
/**
 * StartPageLayout - Simple Layout for Start Page
 *
 * A wrapper for the start page that handles file drag-and-drop.
 */

import type { ReactNode } from "react";
import { useCallback, useEffect, useRef } from "react";
import { useFileDrop } from "@/contexts/file-drop-context";
import { FileDropOverlay } from "./file-drop-overlay";

const THREAD_MAX_WIDTH = "50rem";

interface StartPageLayoutProps {
  children: ReactNode;
}

export function StartPageLayout({ children }: StartPageLayoutProps) {
  const { isDragging, setIsDragging, onFilesDropped } = useFileDrop();
  const dragCounterRef = useRef(0);
  const dragCancelledRef = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Drag-and-drop handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.types && e.dataTransfer.types.includes("Files")) {
      dragCancelledRef.current = false;
      dragCounterRef.current += 1;
      if (dragCounterRef.current === 1) {
        setIsDragging(true);
      }
    }
  }, [setIsDragging]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDragging(false);
    }
  }, [setIsDragging]);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    const wasCancelled = dragCancelledRef.current;
    dragCancelledRef.current = false;
    setIsDragging(false);
    if (wasCancelled) return;
    const files = e.dataTransfer.files;
    if (files && files.length > 0 && onFilesDropped) {
      await onFilesDropped(files);
    }
  }, [setIsDragging, onFilesDropped]);

  useEffect(() => {
    const handleDragEnd = (e: DragEvent) => {
      if (e.dataTransfer && e.dataTransfer.dropEffect === "none") {
        dragCounterRef.current = 0;
        dragCancelledRef.current = true;
        setIsDragging(false);
      }
    };
    window.addEventListener("dragend", handleDragEnd);
    return () => window.removeEventListener("dragend", handleDragEnd);
  }, [setIsDragging]);

  useEffect(() => {
    return () => {
      dragCounterRef.current = 0;
      dragCancelledRef.current = false;
      setIsDragging(false);
    };
  }, [setIsDragging]);

  return (
    <div
      ref={rootRef}
      className="box-border flex h-full flex-col overflow-hidden"
      style={{ ["--thread-max-width" as string]: THREAD_MAX_WIDTH }}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <FileDropOverlay isVisible={isDragging} />
      <div className="flex flex-1 min-h-0 w-full flex-col items-center mobile-scroll bg-inherit px-4 py-4 mobile-container">
        <div className="flex-1 w-full flex flex-col items-center min-h-0">
          {children}
        </div>
      </div>
    </div>
  );
}
