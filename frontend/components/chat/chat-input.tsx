
/**
 * ChatInput - Unified Message Input Component
 *
 * Modes:
 * - "send": Send messages to an existing conversation (requires onSend prop)
 * - "create": Create a new conversation and navigate to it (requires projectId or defaults to personal)
 *
 * Features:
 * - Text input with auto-resize
 * - File attachments (via staged upload API)
 * - Voice input
 * - Send/queue actions
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { useToast } from "@/components/ui/toast";
import { useVoiceRecorder } from "@/hooks/use-voice-recorder";
import { createConversation } from "@/lib/api/auth";
import { useConversationRuntimeManager } from "@/contexts/active-streams-context";
import { searchTaskAssignees, type TaskAssignableUser } from "@/lib/api/tasks";
import { useChatInputAttachments } from "@/components/chat/use-chat-input-attachments";
import { ChatInputView } from "@/components/chat/chat-input-view";
import {
  SLASH_COMMANDS,
  isReadyAttachment,
  toAttachmentMeta,
  type AttachmentMeta,
  type SlashCommand,
} from "@/components/chat/chat-input.shared";
import {
  DEFAULT_CONVERSATION_TITLE,
  toConversationPreviewText,
} from "@/lib/conversation-titles";

type BaseChatInputProps = {
  /** Whether redaction is enabled for uploads */
  redactionEnabled?: boolean;
  /** Callback when redaction changes */
  onRedactionChange?: (value: boolean) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Custom class name */
  className?: string;
  /** Content rendered at the top of the input card (e.g. suggestions, tasks) */
  topContent?: ReactNode;
};

type SendModeProps = BaseChatInputProps & {
  /** Mode: send to existing conversation */
  mode: "send";
  /** Called when user submits a message */
  onSend: (
    content: string,
    options: {
      attachmentIds: string[];
      attachments: AttachmentMeta[];
    }
  ) => void;
  /** Whether the composer is disabled */
  disabled?: boolean;
  /** Whether assistant is currently streaming */
  isStreaming?: boolean;
  /** Conversation ID for file uploads */
  conversationId?: string;
};

type CreateModeProps = BaseChatInputProps & {
  /** Mode: create new conversation */
  mode: "create";
  /** Project ID if creating conversation in a project */
  projectId?: string;
};

export type ChatInputProps = SendModeProps | CreateModeProps;

const MENTION_TOKEN_ESCAPE_PATTERN = /[.*+?^${}()|[\]\\]/g;

function escapeRegExp(value: string): string {
  return value.replace(MENTION_TOKEN_ESCAPE_PATTERN, "\\$&");
}

function createClientConversationId(): string {
  try {
    const generated = crypto?.randomUUID?.();
    if (typeof generated === "string" && generated.trim().length > 0) {
      return generated;
    }
  } catch {}

  const segment = (length: number): string => {
    let value = "";
    while (value.length < length) {
      value += Math.random().toString(16).slice(2);
    }
    return value.slice(0, length);
  };

  return `${segment(8)}-${segment(4)}-4${segment(3)}-a${segment(3)}-${segment(12)}`;
}

// ============================================================================
// ChatInput Component
// ============================================================================

export const ChatInput: FC<ChatInputProps> = (props) => {
  const {
    mode,
    redactionEnabled = false,
    onRedactionChange,
    placeholder = "Ask anything",
    className,
    topContent,
  } = props;

  // Mode-specific props
  const onSend = mode === "send" ? props.onSend : undefined;
  const disabled = mode === "send" ? props.disabled ?? false : false;
  const isStreaming = mode === "send" ? props.isStreaming ?? false : false;
  const conversationId = mode === "send" ? props.conversationId : undefined;
  const projectId = mode === "create" ? props.projectId : undefined;

  const navigate = useNavigate();
  const { addToast } = useToast();
  const runtimeManager = useConversationRuntimeManager();

  // State
  const [text, setText] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [showFileWarningDialog, setShowFileWarningDialog] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionResults, setMentionResults] = useState<TaskAssignableUser[]>([]);
  const [mentionLoading, setMentionLoading] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionHighlightIndex, setMentionHighlightIndex] = useState(0);
  const [draftHydratedKey, setDraftHydratedKey] = useState<string | null>(null);
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState("");
  const [slashHighlightIndex, setSlashHighlightIndex] = useState(0);

  // Refs
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const redactionRef = useRef(redactionEnabled);
  const isSubmittingRef = useRef(false); // Sync guard against double-submit
  const mentionRangeRef = useRef<{ start: number; end: number } | null>(null);
  // Map of display name → email for inserted mentions (used to reconstruct full tokens on send)
  const mentionsMapRef = useRef<Map<string, string>>(new Map());
  const [mentionVersion, setMentionVersion] = useState(0);
  const {
    attachments,
    hasUploadingAttachment,
    handleFilesSelected,
    removeAttachment,
    clearAttachments,
  } = useChatInputAttachments({ redactionRef });

  // Keep redaction ref in sync
  useEffect(() => {
    redactionRef.current = redactionEnabled;
  }, [redactionEnabled]);

  // Derived state
  const canToggleRedaction = typeof onRedactionChange === "function";
  const isEmpty = text.trim() === "" && attachments.length === 0;
  const hasDraftIntent = text.trim() !== "" || attachments.length > 0;
  const isBusy = isCreating;
  const inputsDisabled = disabled || isBusy;
  const sendDisabled = inputsDisabled || isEmpty || hasUploadingAttachment;

  // Bottom toolbar is always visible; rectangular shape always used
  const draftStorageKey = useMemo(() => {
    if (mode === "create") {
      return projectId
        ? `assist:draft:create:project:${projectId}`
        : "assist:draft:create:personal";
    }
    return conversationId
      ? `assist:draft:conversation:${conversationId}`
      : "assist:draft:conversation:unknown";
  }, [mode, projectId, conversationId]);

  const writeDraftToSession = useCallback((storageKey: string, value: string) => {
    try {
      if (value.trim().length === 0) {
        window.sessionStorage.removeItem(storageKey);
      } else {
        window.sessionStorage.setItem(storageKey, value);
      }
    } catch {}
  }, []);

  const clearMentionSearchState = useCallback(() => {
    mentionRangeRef.current = null;
    setMentionQuery("");
    setMentionResults([]);
    setMentionOpen(false);
    setMentionHighlightIndex(0);
  }, []);

  const clearInsertedMentions = useCallback(() => {
    mentionsMapRef.current.clear();
    setMentionVersion(0);
  }, []);

  const clearSlashState = useCallback(() => {
    setSlashOpen(false);
    setSlashQuery("");
    setSlashHighlightIndex(0);
  }, []);

  const clearComposerTextState = useCallback(() => {
    setText("");
    clearInsertedMentions();
    clearMentionSearchState();
    clearSlashState();
    writeDraftToSession(draftStorageKey, "");
  }, [
    clearInsertedMentions,
    clearMentionSearchState,
    clearSlashState,
    draftStorageKey,
    writeDraftToSession,
  ]);

  const resetComposer = useCallback(() => {
    clearComposerTextState();
    clearAttachments();
  }, [clearAttachments, clearComposerTextState]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Restore unsent draft on mount/context change.
  useLayoutEffect(() => {
    let restoredText = "";
    try {
      restoredText = window.sessionStorage.getItem(draftStorageKey) ?? "";
    } catch {
      restoredText = "";
    }
    setText(restoredText);
    clearInsertedMentions();
    clearMentionSearchState();
    clearSlashState();
    setDraftHydratedKey(draftStorageKey);
  }, [clearInsertedMentions, clearMentionSearchState, clearSlashState, draftStorageKey]);

  // Persist unsent draft so refresh doesn't wipe the composer.
  useEffect(() => {
    if (draftHydratedKey !== draftStorageKey) return;
    writeDraftToSession(draftStorageKey, text);
  }, [draftHydratedKey, draftStorageKey, text, writeDraftToSession]);

  // Keyboard shortcut to focus input (Cmd+/ on Mac, Ctrl+/ on Windows)
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      const isSlashKey = e.code === "Slash" || e.key === "/" || e.key === "?";
      if (!isSlashKey || !(e.metaKey || e.ctrlKey)) return;

      e.preventDefault();
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      const len = el.value.length;
      el.setSelectionRange(len, len);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Reset create-mode submission flags after transitioning to send mode.
  useEffect(() => {
    if (mode === "create") return;
    isSubmittingRef.current = false;
    setIsCreating(false);
    clearAttachments();
  }, [clearAttachments, mode]);

  // Track landscape-mobile state reactively so textarea max-height updates on
  // orientation change, not just on the next keystroke.
  const [isLandscapeMobile, setIsLandscapeMobile] = useState(
    () => window.innerWidth < 900 && window.innerHeight < 500,
  );
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 899px) and (max-height: 499px)");
    const onChange = () => setIsLandscapeMobile(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  // Auto-resize textarea (runs on text change AND layout change).
  // On mobile landscape with keyboard, cap height lower so messages stay visible.
  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;

    const maxH = isLandscapeMobile ? 100 : 200;

    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxH)}px`;
  }, [text, isLandscapeMobile]);

  useEffect(() => {
    if (text.length > 0) {
      return;
    }
    clearInsertedMentions();
  }, [clearInsertedMentions, text]);

  const updateMentionContext = useCallback((nextText: string, cursor: number) => {
    const beforeCursor = nextText.slice(0, cursor);
    const match = beforeCursor.match(/(^|\s)@([^\s@]*)$/);
    if (!match) {
      clearMentionSearchState();
      return;
    }

    const query = match[2] ?? "";
    const start = cursor - query.length - 1;
    mentionRangeRef.current = { start, end: cursor };
    setMentionQuery(query);
    setMentionOpen(query.trim().length >= 2);
    setMentionHighlightIndex(0);
  }, [clearMentionSearchState]);

  // Slash command detection — "/" must be the very first character
  const updateSlashContext = useCallback((nextText: string) => {
    const match = nextText.match(/^\/([a-z]*)$/i);
    if (!match) {
      clearSlashState();
      return;
    }
    setSlashQuery((match[1] ?? "").toLowerCase());
    setSlashOpen(true);
    setSlashHighlightIndex(0);
  }, [clearSlashState]);

  // Filtered commands based on query
  const slashFiltered = useMemo(() => {
    const q = slashQuery.toLowerCase();
    return SLASH_COMMANDS
      .filter((cmd) => cmd.label.toLowerCase().includes(q) || cmd.id.startsWith(q));
  }, [slashQuery]);

  // Execute a selected slash command
  const executeSlashCommand = useCallback((cmd: SlashCommand) => {
    clearComposerTextState();

    if (cmd.id === "attach") {
      setShowFileWarningDialog(true);
    }

    requestAnimationFrame(() => inputRef.current?.focus());
  }, [clearComposerTextState]);

  useEffect(() => {
    if (!mentionOpen || mentionQuery.trim().length < 2) {
      setMentionLoading(false);
      setMentionResults([]);
      return;
    }

    let cancelled = false;
    setMentionLoading(true);
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const users = await searchTaskAssignees(mentionQuery.trim(), 8);
          if (cancelled) return;
          setMentionResults(users);
          setMentionHighlightIndex(0);
        } catch {
          if (!cancelled) setMentionResults([]);
        } finally {
          if (!cancelled) setMentionLoading(false);
        }
      })();
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mentionOpen, mentionQuery]);

  const insertMention = useCallback((assignee: TaskAssignableUser) => {
    const range = mentionRangeRef.current;
    const textarea = inputRef.current;
    if (!range || !textarea) return;
    const label = assignee.name?.trim() || assignee.email;
    const token = `@${label} `;
    // Store the name→email mapping so we can reconstruct full tokens on send
    mentionsMapRef.current.set(label, assignee.email);
    setMentionVersion((v) => v + 1);
    const nextText = text.slice(0, range.start) + token + text.slice(range.end);
    const nextCursor = range.start + token.length;
    setText(nextText);
    writeDraftToSession(draftStorageKey, nextText);
    clearMentionSearchState();
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(nextCursor, nextCursor);
    });
  }, [clearMentionSearchState, draftStorageKey, text, writeDraftToSession]);

  // Reconstruct @Name → @Name <email> for all stored mentions before sending
  const resolveContentWithMentions = useCallback((raw: string): string => {
    const map = mentionsMapRef.current;
    if (map.size === 0) return raw;
    let resolved = raw;
    // Replace longest names first to avoid partial matches
    const entries = Array.from(map.entries()).sort((a, b) => b[0].length - a[0].length);
    for (const [name, email] of entries) {
      // Match @Name followed by whitespace or end-of-string (not already followed by <email>)
      const pattern = new RegExp(`@${escapeRegExp(name)}(?!\\s*<)`, "g");
      resolved = resolved.replace(pattern, `@${name} <${email}>`);
    }
    return resolved;
  }, []);

  // Build backdrop content: all text is invisible, mentions get a background highlight
  const hasMentions = mentionVersion > 0 && mentionsMapRef.current.size > 0;
  const mentionBackdrop = useMemo(() => {
    const map = mentionsMapRef.current;
    if (map.size === 0) return null;

    const names = Array.from(map.keys())
      .sort((a, b) => b.length - a.length)
      .map(escapeRegExp);
    if (names.length === 0) return null;

    const pattern = new RegExp(`@(${names.join("|")})`, "g");
    const parts: ReactNode[] = [];
    let lastIndex = 0;
    pattern.lastIndex = 0;
    let m: RegExpExecArray | null;

    while ((m = pattern.exec(text)) !== null) {
      // Non-mention text: transparent (takes up space for alignment, nothing visible)
      if (m.index > lastIndex) {
        parts.push(<span key={`t-${lastIndex}`} className="text-transparent">{text.slice(lastIndex, m.index)}</span>);
      }
      // Mention token: transparent text with visible background highlight
      parts.push(
        <span key={`m-${m.index}`} className="text-transparent bg-primary/15 rounded-[3px] box-decoration-clone">{m[0]}</span>
      );
      lastIndex = m.index + m[0].length;
    }

    if (lastIndex < text.length) {
      parts.push(<span key={`t-${lastIndex}`} className="text-transparent">{text.slice(lastIndex)}</span>);
    }
    return parts.length > 0 ? parts : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, mentionVersion]);

  const syncBackdropScroll = useCallback(() => {
    if (backdropRef.current && inputRef.current) {
      backdropRef.current.scrollTop = inputRef.current.scrollTop;
    }
  }, []);

  // Handle text change
  const handleTextChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      const nextText = e.target.value;
      setText(nextText);
      writeDraftToSession(draftStorageKey, nextText);
      const cursor = e.target.selectionStart ?? nextText.length;
      updateMentionContext(nextText, cursor);
      updateSlashContext(nextText);
    },
    [draftStorageKey, updateMentionContext, updateSlashContext, writeDraftToSession]
  );

  // Handle send (send mode)
  const handleSendMode = useCallback(() => {
    if (sendDisabled || !onSend) return;

    const content = resolveContentWithMentions(text.trim());
    const readyAttachments = attachments.filter(isReadyAttachment);
    const attachmentIds = readyAttachments.map((attachment) => attachment.backendId);
    const attachmentMetas: AttachmentMeta[] = readyAttachments.map(toAttachmentMeta);

    onSend(content, {
      attachmentIds,
      attachments: attachmentMetas,
    });

    resetComposer();
  }, [
    attachments,
    onSend,
    resetComposer,
    resolveContentWithMentions,
    sendDisabled,
    text,
  ]);

  // Handle send (create mode) - creates lightweight conversation metadata,
  // starts the first run through the normal runtime manager path, then navigates.
  const handleCreateMode = useCallback(async () => {
    if (sendDisabled) return;

    // Sync guard to prevent double-submit (state update is async)
    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;

    const content = resolveContentWithMentions(text.trim());
    if (!content) {
      isSubmittingRef.current = false;
      return;
    }

    setIsCreating(true);

    const conversationId = createClientConversationId();
    const createRequestId = `create:${conversationId}`;

    const readyAttachments = attachments.filter(isReadyAttachment);
    const attachmentIds = readyAttachments.map((attachment) => attachment.backendId);
    const readyAttachmentMetas: AttachmentMeta[] = readyAttachments.map(toAttachmentMeta);

    try {
      const conversation = await createConversation({
        conversationId,
        requestId: createRequestId,
        projectId,
      });
      const nowIso = new Date().toISOString();
      const provisionalSidebarPreview = toConversationPreviewText(content);

      try {
        window.dispatchEvent(
          new CustomEvent("frontend:conversationCreated", {
            detail: {
              conversation: {
                ...conversation,
                id: conversation.id,
                title: conversation.title ?? DEFAULT_CONVERSATION_TITLE,
                updated_at: conversation.updated_at ?? nowIso,
                last_message_at: nowIso,
                message_count: Math.max(conversation.message_count ?? 0, 1),
                last_message_preview: provisionalSidebarPreview,
                created_at: conversation.created_at ?? nowIso,
                project_id: conversation.project_id ?? projectId ?? null,
              },
            },
          })
        );
      } catch {}

      void runtimeManager.sendMessage(conversationId, content, {
        attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
        attachments: readyAttachmentMetas,
      }).catch((error) => {
        const message = error instanceof Error ? error.message : "Failed to send the first message";
        addToast({
          type: "error",
          title: "Couldn't send first message",
          description: message,
        });
      });

      resetComposer();

      const href = projectId ? `/projects/${projectId}/chat/${conversationId}` : `/chat/${conversationId}`;
      try {
        navigate(href, { replace: true });
      } catch {
        window.location.replace(href);
      }
    } catch (err) {
      const message = (err as Error)?.message || "Failed to start chat";
      addToast({
        type: "error",
        title: "Couldn't start chat",
        description: message,
      });
      setIsCreating(false);
      isSubmittingRef.current = false;
    }
  }, [
    sendDisabled,
    text,
    attachments,
    projectId,
    navigate,
    addToast,
    resetComposer,
    runtimeManager,
    resolveContentWithMentions,
  ]);

  // Unified send handler
  const handleSend = useCallback(() => {
    if (mode === "send") {
      handleSendMode();
    } else {
      handleCreateMode();
    }
  }, [mode, handleSendMode, handleCreateMode]);

  const handleStop = useCallback(() => {
    if (mode !== "send" || !conversationId) {
      return;
    }
    void runtimeManager.stopActiveRun(conversationId).catch((error) => {
      const message = error instanceof Error ? error.message : "Failed to stop response";
      addToast({
        type: "error",
        title: "Couldn't stop response",
        description: message,
      });
    });
  }, [addToast, conversationId, mode, runtimeManager]);

  // Handle key down
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Slash command navigation
      if (slashOpen && slashFiltered.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSlashHighlightIndex((prev) => (prev + 1) % slashFiltered.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSlashHighlightIndex((prev) => (prev - 1 + slashFiltered.length) % slashFiltered.length);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          clearSlashState();
          return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          const selected = slashFiltered[slashHighlightIndex] ?? slashFiltered[0];
          if (selected) executeSlashCommand(selected);
          return;
        }
        if (e.key === "Tab") {
          e.preventDefault();
          const selected = slashFiltered[slashHighlightIndex] ?? slashFiltered[0];
          if (selected) executeSlashCommand(selected);
          return;
        }
      }

      if (mentionOpen) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          if (mentionResults.length > 0) {
            setMentionHighlightIndex((prev) => (prev + 1) % mentionResults.length);
          }
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          if (mentionResults.length > 0) {
            setMentionHighlightIndex((prev) => (prev - 1 + mentionResults.length) % mentionResults.length);
          }
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          clearMentionSearchState();
          return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
          if (mentionResults.length > 0) {
            e.preventDefault();
            const selected = mentionResults[mentionHighlightIndex] ?? mentionResults[0];
            if (selected) insertMention(selected);
            return;
          }
        }
      }

      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!sendDisabled) {
          handleSend();
        } else if (hasUploadingAttachment) {
          addToast({
            type: "info",
            title: "Please wait",
            description: "Files are still uploading.",
          });
        }
      }
    },
    [
      slashOpen,
      slashFiltered,
      slashHighlightIndex,
      executeSlashCommand,
      clearSlashState,
      mentionOpen,
      mentionResults,
      mentionHighlightIndex,
      insertMention,
      clearMentionSearchState,
      sendDisabled,
      hasUploadingAttachment,
      addToast,
      handleSend,
    ]
  );

  // Handle attachment button
  const handleAttachmentButton = useCallback(() => {
    requestAnimationFrame(() => {
      setShowFileWarningDialog(true);
    });
  }, []);

  const handleFileWarningConfirm = useCallback(() => {
    fileInputRef.current?.click();
    setShowFileWarningDialog(false);
  }, []);

  const handleFileWarningClose = useCallback(() => {
    setShowFileWarningDialog(false);
  }, []);

  // Voice input
  const handleVoiceError = useCallback(
    (message: string) => {
      addToast({ type: "error", title: "Voice input", description: message });
    },
    [addToast]
  );

  const handleVoiceTranscription = useCallback(
    (rawText: string) => {
      const transcribed = rawText?.trim();
      if (!transcribed) {
        addToast({
          type: "error",
          title: "Voice input",
          description: "No speech detected.",
        });
        return;
      }

      setText((prev) => {
        const needsSpace = prev && !prev.endsWith(" ") && !prev.endsWith("\n");
        const nextText = prev + (needsSpace ? " " : "") + transcribed;
        writeDraftToSession(draftStorageKey, nextText);
        return nextText;
      });
    },
    [addToast, draftStorageKey, writeDraftToSession]
  );

  const {
    isRecording,
    isTranscribing,
    startRecording,
    stopRecording,
    permissionState,
  } = useVoiceRecorder({
    onTranscription: handleVoiceTranscription,
    onError: handleVoiceError,
  });

  const handleMicClick = useCallback(async () => {
    if (isRecording) {
      stopRecording();
    } else {
      await startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  const voiceTooltipLabel = isRecording
    ? "Stop recording"
    : permissionState === "denied"
      ? "Enable microphone access"
      : "Start voice input";

  const voiceDisabled = inputsDisabled || hasUploadingAttachment || isTranscribing;

  const refreshMentionFromCursor = useCallback(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    const cursor = textarea.selectionStart ?? textarea.value.length;
    updateMentionContext(textarea.value, cursor);
  }, [updateMentionContext]);

  return (
    <ChatInputView
      className={className}
      topContent={topContent}
      placeholder={placeholder}
      fileInputRef={fileInputRef}
      inputRef={inputRef}
      backdropRef={backdropRef}
      inputsDisabled={inputsDisabled}
      text={text}
      attachments={attachments}
      hasMentions={hasMentions}
      mentionBackdrop={mentionBackdrop}
      slashOpen={slashOpen}
      slashFiltered={slashFiltered}
      slashHighlightIndex={slashHighlightIndex}
      mentionOpen={mentionOpen}
      mentionLoading={mentionLoading}
      mentionResults={mentionResults}
      mentionHighlightIndex={mentionHighlightIndex}
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
      showFileWarningDialog={showFileWarningDialog}
      canToggleRedaction={canToggleRedaction}
      redactionEnabled={redactionEnabled}
      onRedactionChange={onRedactionChange}
      onFilesSelected={handleFilesSelected}
      onTextChange={handleTextChange}
      onKeyDown={handleKeyDown}
      onRefreshMentionFromCursor={refreshMentionFromCursor}
      onSyncBackdropScroll={syncBackdropScroll}
      onAttachmentButtonClick={handleAttachmentButton}
      onSlashHighlightIndexChange={setSlashHighlightIndex}
      onExecuteSlashCommand={executeSlashCommand}
      onInsertMention={insertMention}
      onMentionHighlightIndexChange={setMentionHighlightIndex}
      onRemoveAttachment={removeAttachment}
      onMicClick={handleMicClick}
      onSend={handleSend}
      onStop={handleStop}
      onFileWarningClose={handleFileWarningClose}
      onFileWarningConfirm={handleFileWarningConfirm}
    />
  );
};
