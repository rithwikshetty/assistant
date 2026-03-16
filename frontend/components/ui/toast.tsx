
import * as React from "react";
import { X, CheckCircle, WarningCircle, Info } from "@phosphor-icons/react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  type?: 'success' | 'error' | 'info';
  duration?: number;
}

interface ToastContextProps {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextProps | undefined>(undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const addToast = React.useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).substring(2, 9);
    const newToast = { ...toast, id };
    setToasts(prev => [...prev, newToast]);

    const duration = toast.duration ?? 3000;
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, duration);
  }, []);

  const removeToast = React.useCallback((id: string) => {
    setToasts(prev => prev.filter(toast => toast.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      <ToastContainer />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = React.useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

function ToastContainer() {
  const { toasts } = useToast();

  return (
    <div className="fixed top-0 right-0 z-50 w-full max-w-sm p-4 pointer-events-none">
      <div className="space-y-2">
        <AnimatePresence mode="popLayout" initial={false}>
          {toasts.map(toast => (
            <ToastItem key={toast.id} toast={toast} />
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

function ToastItem({ toast }: { toast: Toast }) {
  const { removeToast } = useToast();

  const iconMap = {
    success: CheckCircle,
    error: WarningCircle,
    info: Info,
  };

  const Icon = toast.type ? iconMap[toast.type] : Info;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 80, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 80, scale: 0.95 }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
      className={cn(
        "pointer-events-auto relative flex w-full items-center space-x-3 rounded-xl border p-4 shadow-lg",
        "bg-background border-border/40 text-foreground backdrop-blur-lg",
        toast.type === 'success' && "bg-[var(--toast-success)] text-[color:var(--toast-success-foreground)] border-transparent",
        toast.type === 'error' && "bg-[var(--toast-error)] text-[color:var(--toast-error-foreground)] border-transparent",
        toast.type === 'info' && "bg-[var(--toast-info)] text-[color:var(--toast-info-foreground)] border-transparent",
      )}
    >
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 500, damping: 25, delay: 0.1 }}
      >
        <Icon className={cn("size-5 shrink-0 text-current")} weight="duotone" />
      </motion.div>

      <div className="flex-1 min-w-0">
        {toast.title && (
          <div className="type-size-14 font-medium text-current">
            {toast.title}
          </div>
        )}
        {toast.description && (
          <div className="type-size-12 text-current/80 mt-0.5">
            {toast.description}
          </div>
        )}
      </div>

      <Button
        variant="ghost"
        size="icon"
        onClick={() => removeToast(toast.id)}
        className="size-6 rounded-lg text-current/60 hover:text-current hover:bg-transparent"
      >
        <X className="size-3.5" />
        <span className="sr-only">Close</span>
      </Button>
    </motion.div>
  );
}
