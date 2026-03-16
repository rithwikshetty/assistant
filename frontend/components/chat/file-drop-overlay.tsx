
import { AnimatePresence, motion } from "framer-motion";
import { FileArrowUp, Upload } from "@phosphor-icons/react";
import { MAX_FILE_SIZE_MB } from "@/lib/file-types";

type FileDropOverlayProps = {
  isVisible: boolean;
};

export function FileDropOverlay({ isVisible }: FileDropOverlayProps) {

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="pointer-events-none fixed inset-0 z-50 overflow-hidden"
          aria-hidden="true"
        >
          <motion.div
            className="absolute inset-0 bg-background/92"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
          />
          <motion.div
            className="absolute inset-0 bg-[radial-gradient(circle_at_30%_25%,rgba(194,65,12,0.18),transparent_58%),radial-gradient(circle_at_70%_75%,rgba(251,146,60,0.16),transparent_60%)]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.45 }}
          />
          <motion.div
            className="absolute inset-0 bg-[linear-gradient(160deg,rgba(28,25,23,0.45),rgba(120,53,15,0.30),rgba(28,25,23,0.45))]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.85 }}
            transition={{ duration: 0.5 }}
          />
          <motion.div
            className="absolute -left-1/4 top-1/2 h-[120%] w-[55%] -translate-y-1/2 rounded-[40%] bg-primary/20 blur-3xl"
            animate={{ rotate: [0, 8, -8, 0] }}
            transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
          />
          <motion.div
            className="absolute -right-1/4 top-1/2 h-[130%] w-[50%] -translate-y-1/2 rounded-[45%] bg-primary/15 blur-3xl"
            animate={{ rotate: [0, -10, 6, 0] }}
            transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
          />
          <motion.div
            className="absolute inset-x-[18%] top-12 h-28 rounded-full bg-white/10 blur-[140px]"
            animate={{ opacity: [0.25, 0.55, 0.25], y: [-16, 0, -16] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
          />
          <motion.div
            className="absolute inset-x-[24%] bottom-12 h-1/3 rounded-3xl bg-primary/12 blur-[140px]"
            animate={{ opacity: [0.18, 0.38, 0.18], scale: [0.95, 1.07, 0.95] }}
            transition={{ duration: 6.5, repeat: Infinity, ease: "easeInOut" }}
          />

          <motion.div
            className="relative z-10 flex h-full flex-col items-center justify-center gap-8 px-6 text-center"
            animate={{ y: [0, -8, 0] }}
            transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
          >
            <div className="relative flex h-32 w-32 items-center justify-center">
              <motion.div
                className="flex h-24 w-24 items-center justify-center rounded-2xl border border-white/15 bg-white/10 shadow-[0_25px_60px_-40px_rgba(28,25,23,1)] backdrop-blur-2xl"
                animate={{
                  scale: [1, 1.04, 1],
                  rotate: [0, 3, -3, 0],
                }}
                transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
              >
                <FileArrowUp className="h-12 w-12 text-primary" />
              </motion.div>
            </div>

            <div className="space-y-2">
              <motion.p
                className="type-size-32 font-semibold tracking-tight text-foreground"
                initial={{ y: 8, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.1, duration: 0.25, ease: "easeOut" }}
              >
                Drop files anywhere to attach
              </motion.p>
              <motion.p
                className="type-size-14 text-muted-foreground/90"
                initial={{ y: 8, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.2, duration: 0.25, ease: "easeOut" }}
              >
                {`PDF, DOCX, XLSX, PPTX, TXT, PNG, JPG · Max 10 files · ${MAX_FILE_SIZE_MB}MB each`}
              </motion.p>
            </div>

            <motion.div
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/10 px-4 py-1.5 type-size-12 font-medium text-muted-foreground/90 backdrop-blur-xl"
              animate={{ opacity: [0.6, 1, 0.6] }}
              transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
            >
              <Upload className="h-3.5 w-3.5 text-primary/80" weight="bold" />
              Drag & drop to upload securely
            </motion.div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
