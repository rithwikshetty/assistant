import {
  type ChangeEvent,
  type FC,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import {
  Warning,
  ArrowUp,
  Check,
  FileText,
  SpinnerGap,
  Microphone,
  Plus,
  Square,
  X,
} from "@phosphor-icons/react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FileUploadWarningDialog } from "@/components/ui/file-upload-warning-dialog";
import { FILE_ACCEPT_STRING } from "@/lib/file-types";
import { formatBytes } from "@/lib/attachments";
import type { TaskAssignableUser } from "@/lib/api/tasks";
import type { Attachment, SlashCommand } from "@/components/chat/chat-input.shared";

type ChatInputViewProps = {
  className?: string;
  topContent?: ReactNode;
  placeholder: string;
  fileInputRef: RefObject<HTMLInputElement | null>;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  backdropRef: RefObject<HTMLDivElement | null>;
  inputsDisabled: boolean;
  text: string;
  attachments: Attachment[];
  hasMentions: boolean;
  mentionBackdrop: ReactNode | null;
  slashOpen: boolean;
  slashFiltered: SlashCommand[];
  slashHighlightIndex: number;
  mentionOpen: boolean;
  mentionLoading: boolean;
  mentionResults: TaskAssignableUser[];
  mentionHighlightIndex: number;
  mode: "send" | "create";
  isStreaming: boolean;
  hasDraftIntent: boolean;
  sendDisabled: boolean;
  hasUploadingAttachment: boolean;
  isCreating: boolean;
  isTranscribing: boolean;
  isRecording: boolean;
  voiceTooltipLabel: string;
  voiceDisabled: boolean;
  showFileWarningDialog: boolean;
  canToggleRedaction: boolean;
  redactionEnabled: boolean;
  onRedactionChange?: (value: boolean) => void;
  onFilesSelected: (event: ChangeEvent<HTMLInputElement>) => void | Promise<void>;
  onTextChange: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onRefreshMentionFromCursor: () => void;
  onSyncBackdropScroll: () => void;
  onAttachmentButtonClick: () => void;
  onSlashHighlightIndexChange: (index: number) => void;
  onExecuteSlashCommand: (command: SlashCommand) => void;
  onInsertMention: (assignee: TaskAssignableUser) => void;
  onMentionHighlightIndexChange: (index: number) => void;
  onRemoveAttachment: (id: string) => void | Promise<void>;
  onMicClick: () => void | Promise<void>;
  onSend: () => void;
  onStop?: () => void;
  onFileWarningClose: () => void;
  onFileWarningConfirm: () => void;
};

export const ChatInputView: FC<ChatInputViewProps> = ({
  className,
  topContent,
  placeholder,
  fileInputRef,
  inputRef,
  backdropRef,
  inputsDisabled,
  text,
  attachments,
  hasMentions,
  mentionBackdrop,
  slashOpen,
  slashFiltered,
  slashHighlightIndex,
  mentionOpen,
  mentionLoading,
  mentionResults,
  mentionHighlightIndex,
  mode,
  isStreaming,
  hasDraftIntent,
  sendDisabled,
  hasUploadingAttachment,
  isCreating,
  isTranscribing,
  isRecording,
  voiceTooltipLabel,
  voiceDisabled,
  showFileWarningDialog,
  canToggleRedaction,
  redactionEnabled,
  onRedactionChange,
  onFilesSelected,
  onTextChange,
  onKeyDown,
  onRefreshMentionFromCursor,
  onSyncBackdropScroll,
  onAttachmentButtonClick,
  onSlashHighlightIndexChange,
  onExecuteSlashCommand,
  onInsertMention,
  onMentionHighlightIndexChange,
  onRemoveAttachment,
  onMicClick,
  onSend,
  onStop,
  onFileWarningClose,
  onFileWarningConfirm,
}) => {
  return (
    <TooltipProvider>
      <div className={cn("w-full", className)}>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          multiple
          accept={FILE_ACCEPT_STRING}
          onChange={onFilesSelected}
        />

        <div className="relative">
          {topContent != null && (
            <div className="absolute bottom-full left-[2.5%] right-[2.5%] z-20">
              <div className="rounded-t-xl border border-b-0 border-border/60 bg-background/80 backdrop-blur-sm overflow-hidden">
                {topContent}
              </div>
            </div>
          )}

          <div
            className={cn(
              "focus-glow relative flex w-full flex-col gap-0 rounded-2xl border border-border/60 bg-card px-4 pt-2.5 pb-2.5 shadow-[0_2px_24px_-4px_rgba(0,0,0,0.08),0_0_0_1px_rgba(0,0,0,0.03)]",
              "transition-all duration-300",
              "focus-within:border-primary/20 focus-within:shadow-[0_4px_32px_-4px_rgba(194,65,12,0.12),0_0_0_1px_rgba(194,65,12,0.08)]",
              "dark:shadow-[0_2px_24px_-4px_rgba(0,0,0,0.3),0_0_0_1px_rgba(255,255,255,0.04)]",
              "dark:focus-within:shadow-[0_4px_32px_-4px_rgba(251,146,60,0.15),0_0_0_1px_rgba(251,146,60,0.1)]"
            )}
          >
            <AttachmentList
              attachments={attachments}
              onRemoveAttachment={onRemoveAttachment}
            />

            <div
              className="grid min-w-0 flex-1"
              style={{ gridTemplate: "1fr / 1fr" }}
            >
              {hasMentions && mentionBackdrop != null && (
                <div
                  ref={backdropRef}
                  aria-hidden
                  className="pointer-events-none overflow-hidden whitespace-pre-wrap break-words border-0 type-chat-input min-h-10"
                  style={{ gridArea: "1/1", padding: "2px 0", margin: 0 }}
                >
                  {mentionBackdrop}
                </div>
              )}

              <textarea
                ref={inputRef}
                value={text}
                onChange={onTextChange}
                onKeyDown={onKeyDown}
                onKeyUp={onRefreshMentionFromCursor}
                onClick={onRefreshMentionFromCursor}
                onScroll={onSyncBackdropScroll}
                placeholder={placeholder}
                disabled={inputsDisabled}
                rows={2}
                name="input"
                className={cn(
                  "w-full resize-none border-0 bg-transparent outline-none focus:ring-0",
                  "min-h-10 type-chat-input",
                  "placeholder:text-muted-foreground/50",
                  "text-foreground caret-foreground selection:bg-primary/20"
                )}
                style={{ gridArea: "1/1", padding: "2px 0", margin: 0 }}
              />

              <SlashCommandMenu
                open={slashOpen}
                commands={slashFiltered}
                highlightIndex={slashHighlightIndex}
                onHighlightIndexChange={onSlashHighlightIndexChange}
                onExecute={onExecuteSlashCommand}
              />

              <MentionSuggestionsMenu
                open={mentionOpen}
                loading={mentionLoading}
                results={mentionResults}
                highlightIndex={mentionHighlightIndex}
                onHighlightIndexChange={onMentionHighlightIndexChange}
                onInsertMention={onInsertMention}
              />
            </div>

            <ChatInputToolbar
              inputsDisabled={inputsDisabled}
              mode={mode}
              isStreaming={isStreaming}
              hasDraftIntent={hasDraftIntent}
              sendDisabled={sendDisabled}
              hasUploadingAttachment={hasUploadingAttachment}
              isCreating={isCreating}
              isTranscribing={isTranscribing}
              isRecording={isRecording}
              voiceTooltipLabel={voiceTooltipLabel}
              voiceDisabled={voiceDisabled}
              onAttachmentButtonClick={onAttachmentButtonClick}
              onMicClick={onMicClick}
              onSend={onSend}
              onStop={onStop}
            />
          </div>
        </div>

        <p className="mt-2.5 text-center type-caption text-muted-foreground/40">
          assistant can make mistakes. Verify important information.
        </p>

        <FileUploadWarningDialog
          open={showFileWarningDialog}
          onClose={onFileWarningClose}
          onConfirm={onFileWarningConfirm}
          showRedactionToggle={canToggleRedaction}
          redactionEnabled={redactionEnabled}
          onRedactionChange={onRedactionChange}
          redactionDisabled={inputsDisabled}
        />
      </div>
    </TooltipProvider>
  );
};

type AttachmentListProps = {
  attachments: Attachment[];
  onRemoveAttachment: (id: string) => void | Promise<void>;
};

const AttachmentList: FC<AttachmentListProps> = ({
  attachments,
  onRemoveAttachment,
}) => {
  if (attachments.length === 0) {
    return null;
  }

  return (
    <div className="mb-2 overflow-x-auto scrollbar-thin">
      <div className="flex items-center gap-2 pb-0.5">
        {attachments.map((attachment) => (
          <AttachmentChip
            key={attachment.id}
            attachment={attachment}
            onRemove={() => onRemoveAttachment(attachment.id)}
          />
        ))}
      </div>
    </div>
  );
};

type SlashCommandMenuProps = {
  open: boolean;
  commands: SlashCommand[];
  highlightIndex: number;
  onHighlightIndexChange: (index: number) => void;
  onExecute: (command: SlashCommand) => void;
};

const SlashCommandMenu: FC<SlashCommandMenuProps> = ({
  open,
  commands,
  highlightIndex,
  onHighlightIndexChange,
  onExecute,
}) => {
  return (
    <AnimatePresence>
      {open && commands.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.96 }}
          transition={{ type: "spring", stiffness: 400, damping: 28 }}
          className="absolute bottom-full left-0 z-50 mb-1 w-56 overflow-hidden rounded-xl border bg-popover py-1 text-popover-foreground shadow-lg backdrop-blur-xl"
          role="listbox"
          aria-label="Slash commands"
        >
          {commands.map((command, index) => {
            const Icon = command.icon;
            return (
              <motion.button
                key={command.id}
                type="button"
                role="option"
                aria-selected={index === highlightIndex}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.03, duration: 0.2 }}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
                  index === highlightIndex ? "bg-muted/60" : "hover:bg-muted/30"
                )}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => onHighlightIndexChange(index)}
                onClick={() => onExecute(command)}
              >
                <Icon className="size-[18px] shrink-0 text-foreground" />
                <span className="type-body text-foreground">{command.label}</span>
              </motion.button>
            );
          })}
        </motion.div>
      )}
    </AnimatePresence>
  );
};

type MentionSuggestionsMenuProps = {
  open: boolean;
  loading: boolean;
  results: TaskAssignableUser[];
  highlightIndex: number;
  onHighlightIndexChange: (index: number) => void;
  onInsertMention: (assignee: TaskAssignableUser) => void;
};

const MentionSuggestionsMenu: FC<MentionSuggestionsMenuProps> = ({
  open,
  loading,
  results,
  highlightIndex,
  onHighlightIndexChange,
  onInsertMention,
}) => {
  if (!open) {
    return null;
  }

  return (
    <div className="absolute bottom-full left-0 right-0 z-50 mb-1 max-h-52 overflow-y-auto rounded-xl border bg-popover text-popover-foreground shadow-lg">
      {loading ? (
        <div className="px-3 py-2 type-caption text-muted-foreground">
          Searching people
        </div>
      ) : results.length > 0 ? (
        <div role="listbox" aria-label="Mention suggestions">
          {results.map((assignee, index) => {
            const label = assignee.name || assignee.email;
            const initials = label
              .split(/[\s.@]+/)
              .filter(Boolean)
              .slice(0, 2)
              .map((segment) => segment[0])
              .join("")
              .toUpperCase();

            return (
              <button
                key={assignee.id}
                type="button"
                role="option"
                aria-selected={index === highlightIndex}
                className={cn(
                  "flex w-full items-center gap-2.5 px-3 py-2 text-left type-body transition-colors",
                  index === highlightIndex ? "bg-muted/60" : "hover:bg-muted/30"
                )}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => onHighlightIndexChange(index)}
                onClick={() => onInsertMention(assignee)}
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary type-control-compact">
                  {initials}
                </span>
                <div className="min-w-0">
                  <div className="truncate type-control">
                    {assignee.name || assignee.email}
                  </div>
                  <div className="truncate type-caption text-muted-foreground">
                    {assignee.email}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="px-3 py-2 type-caption text-muted-foreground">
          No matching active users.
        </div>
      )}
    </div>
  );
};

type ChatInputToolbarProps = {
  inputsDisabled: boolean;
  mode: "send" | "create";
  isStreaming: boolean;
  hasDraftIntent: boolean;
  sendDisabled: boolean;
  hasUploadingAttachment: boolean;
  isCreating: boolean;
  isTranscribing: boolean;
  isRecording: boolean;
  voiceTooltipLabel: string;
  voiceDisabled: boolean;
  onAttachmentButtonClick: () => void;
  onMicClick: () => void | Promise<void>;
  onSend: () => void;
  onStop?: () => void;
};

const ChatInputToolbar: FC<ChatInputToolbarProps> = ({
  inputsDisabled,
  mode,
  isStreaming,
  hasDraftIntent,
  sendDisabled,
  hasUploadingAttachment,
  isCreating,
  isTranscribing,
  isRecording,
  voiceTooltipLabel,
  voiceDisabled,
  onAttachmentButtonClick,
  onMicClick,
  onSend,
  onStop,
}) => {
  const showStopButton =
    mode === "send" &&
    isStreaming &&
    !hasDraftIntent &&
    typeof onStop === "function";
  const sendTooltipLabel =
    hasUploadingAttachment
      ? "Please wait for uploads"
      : sendDisabled
        ? (mode === "send" && isStreaming ? "Type a message to queue" : "Type a message to send")
        : mode === "send" && isStreaming && hasDraftIntent
          ? "Queue message"
          : "Send message";

  return (
    <div className="mt-0 flex items-center justify-between pt-1">
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-full text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          disabled={inputsDisabled}
          aria-label="Add photos & files"
          onClick={onAttachmentButtonClick}
        >
          <Plus className="size-[18px]" aria-hidden="true" />
        </Button>
      </div>

      <div className="flex items-center gap-1.5">
        {isTranscribing && (
          <div className="flex items-center gap-1.5 type-caption text-muted-foreground">
            <div className="flex gap-1" aria-hidden="true">
              <span
                className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
                style={{ animationDelay: "0ms" }}
              />
              <span
                className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
                style={{ animationDelay: "150ms" }}
              />
              <span
                className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
                style={{ animationDelay: "300ms" }}
              />
            </div>
            <span>Transcribing</span>
          </div>
        )}

        {isCreating ? (
          <Button
            size="icon"
            variant="default"
            disabled
            className="h-10 w-10 rounded-full bg-foreground text-background md:h-9 md:w-9"
            aria-label="Starting chat"
          >
            <SpinnerGap className="size-4 animate-spin" aria-hidden="true" />
          </Button>
        ) : (
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onMicClick}
                  className={cn(
                    "h-10 w-10 rounded-full transition-all md:h-9 md:w-9",
                    isRecording
                      ? "animate-pulse bg-red-500 text-white hover:bg-red-600"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  )}
                  disabled={voiceDisabled}
                  aria-pressed={isRecording}
                  aria-label={voiceTooltipLabel}
                >
                  <Microphone
                    className={cn("size-[18px]", isRecording && "text-white")}
                    aria-hidden="true"
                  />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{voiceTooltipLabel}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <AnimatePresence mode="wait" initial={false}>
                  {showStopButton ? (
                    <motion.div
                      key="stop"
                      initial={{ scale: 0.8, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0.8, opacity: 0 }}
                      transition={{ type: "spring", stiffness: 500, damping: 30 }}
                    >
                      <Button
                        size="icon"
                        variant="default"
                        className="h-10 w-10 rounded-full bg-foreground text-background transition-all shadow-md hover:bg-foreground/90 md:h-9 md:w-9"
                        onClick={onStop}
                        aria-label="Stop response"
                      >
                        <Square
                          className="size-3.5"
                          aria-hidden="true"
                          weight="fill"
                        />
                      </Button>
                    </motion.div>
                  ) : (
                    <motion.div
                      key="send"
                      initial={{ scale: 0.8, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0.8, opacity: 0 }}
                      transition={{ type: "spring", stiffness: 500, damping: 30 }}
                    >
                      <Button
                        size="icon"
                        variant="default"
                        className={cn(
                          "h-10 w-10 rounded-full bg-foreground text-background transition-all md:h-9 md:w-9",
                          sendDisabled
                            ? "scale-95 opacity-30"
                            : "opacity-100 shadow-md hover:bg-foreground/90 active:scale-95"
                        )}
                        disabled={sendDisabled}
                        onClick={onSend}
                      >
                        <ArrowUp className="size-4" aria-hidden="true" weight="bold" />
                      </Button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </TooltipTrigger>
              <TooltipContent>
                <p>{showStopButton ? "Stop response" : sendTooltipLabel}</p>
              </TooltipContent>
            </Tooltip>
          </>
        )}
      </div>
    </div>
  );
};

type AttachmentChipProps = {
  attachment: Attachment;
  onRemove: () => void | Promise<void>;
};

const AttachmentChip: FC<AttachmentChipProps> = ({ attachment, onRemove }) => {
  const displayName = attachment.meta?.original_filename || attachment.name;
  const sizeLabel = formatBytes(attachment.meta?.file_size ?? attachment.size);

  return (
    <div
      className={cn(
        "group/chip flex max-w-[220px] flex-shrink-0 items-center gap-2.5 rounded-xl border pl-2.5 pr-1.5 py-1.5",
        "transition-colors duration-150",
        attachment.status === "error"
          ? "border-destructive/30 bg-destructive/5"
          : "border-border/50 bg-muted/30 hover:border-border/80 hover:bg-muted/50"
      )}
    >
      <div
        className={cn(
          "flex size-8 flex-shrink-0 items-center justify-center rounded-lg",
          attachment.status === "error"
            ? "bg-destructive/10 text-destructive"
            : "bg-primary/8 text-primary/70"
        )}
      >
        <FileText className="size-4" aria-hidden="true" />
      </div>

      <div className="min-w-0 flex-1">
        <span
          className="block truncate text-foreground type-control-compact leading-snug"
          title={displayName}
        >
          {displayName}
        </span>
        <div className="mt-0.5 flex items-center gap-1.5 type-nav-meta">
          {sizeLabel && (
            <span className="whitespace-nowrap text-muted-foreground/70">
              {sizeLabel}
            </span>
          )}
          {sizeLabel && (
            <span className="text-muted-foreground/30" aria-hidden="true">
              &middot;
            </span>
          )}
          {attachment.status === "uploading" && (
            <span className="flex items-center gap-1 whitespace-nowrap text-muted-foreground">
              <SpinnerGap className="size-3 animate-spin" aria-hidden="true" />
              <span>Uploading</span>
            </span>
          )}
          {attachment.status === "processing" && (
            <span className="flex items-center gap-1 whitespace-nowrap text-muted-foreground">
              <SpinnerGap className="size-3 animate-spin" aria-hidden="true" />
              <span>Processing</span>
            </span>
          )}
          {attachment.status === "ready" && (
            <span className="flex items-center gap-1 whitespace-nowrap text-emerald-600 dark:text-emerald-400">
              <Check className="size-3" aria-hidden="true" />
              <span>Ready</span>
            </span>
          )}
          {attachment.status === "error" && (
            <span className="flex items-center gap-1 whitespace-nowrap text-destructive">
              <Warning className="size-3" aria-hidden="true" />
              <span>Failed</span>
            </span>
          )}
        </div>
      </div>

      <button
        type="button"
        className={cn(
          "flex size-6 flex-shrink-0 items-center justify-center rounded-full",
          "opacity-0 text-muted-foreground/50 transition-all duration-150",
          "hover:bg-foreground/10 hover:text-foreground",
          "group-hover/chip:opacity-100 focus-visible:opacity-100",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        )}
        aria-label={`Remove ${displayName}`}
        onClick={() => {
          void onRemove();
        }}
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
};
