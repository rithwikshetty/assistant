
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type FileDropContextType = {
  isDragging: boolean;
  setIsDragging: (value: boolean) => void;
  onFilesDropped: ((files: FileList) => Promise<void>) | null;
  registerFileHandler: (handler: (files: FileList) => Promise<void>) => void;
  unregisterFileHandler: () => void;
};

const FileDropContext = createContext<FileDropContextType | null>(null);

export function FileDropProvider({ children }: { children: ReactNode }) {
  const [isDragging, setIsDragging] = useState(false);
  const [fileHandler, setFileHandler] = useState<((files: FileList) => Promise<void>) | null>(null);

  const registerFileHandler = useCallback((handler: (files: FileList) => Promise<void>) => {
    setFileHandler(() => handler);
  }, []);

  const unregisterFileHandler = useCallback(() => {
    setFileHandler(null);
  }, []);

  return (
    <FileDropContext.Provider
      value={{
        isDragging,
        setIsDragging,
        onFilesDropped: fileHandler,
        registerFileHandler,
        unregisterFileHandler,
      }}
    >
      {children}
    </FileDropContext.Provider>
  );
}

export function useFileDrop() {
  const context = useContext(FileDropContext);
  if (!context) {
    throw new Error("useFileDrop must be used within FileDropProvider");
  }
  return context;
}
