
/**
 * UserInputOverlay - Replaces the chat composer when structured user input is pending.
 *
 * Supports options-first question flows with optional free text.
 *
 * Keyboard support:
 *   - ↑↓ navigate options, ←→ navigate questions, 1-9 quick-select,
 *     Enter to continue/submit, Escape to dismiss.
 */

import { useState, useCallback, useEffect, useMemo, useRef, type FC } from "react";
import { Info, SpinnerGap } from "@phosphor-icons/react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cancelRun, submitRunUserInput } from "@/lib/api/chat";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import type { UserInputPayload } from "@/hooks/use-chat";
import {
  isRequestUserInputPendingRequestTransport,
  type RequestUserInputPendingRequestTransport,
  type RequestUserInputSubmissionPayload,
} from "@/lib/contracts/chat-interactive";
import { isComposerInteractiveToolName } from "@/lib/tools/constants";

// ============================================================================
// Types
// ============================================================================

type UserInputQuestionOption = {
  label: string;
  description: string;
};

type UserInputQuestion = {
  id: string;
  question: string;
  options: UserInputQuestionOption[];
};

export type UserInputOverlayProps = {
  payload: UserInputPayload;
  onSubmitted: () => void;
};

type UserInputRequest = RequestUserInputPendingRequestTransport;
type UserInputSubmitResult = {
  success: boolean;
  tool_call_id: string;
  resumed?: boolean;
  started_new_run?: boolean;
  cancelled?: boolean;
};

// ============================================================================
// Shared helpers
// ============================================================================

/** Check if keyboard event target is an input element */
function isInputFocused(e: KeyboardEvent): boolean {
  const target = e.target as HTMLElement;
  return (
    target.tagName === "TEXTAREA" ||
    target.tagName === "INPUT" ||
    target.isContentEditable
  );
}

// ============================================================================
// Session draft persistence
// ============================================================================

const STORAGE_PREFIX = "assist:user-input:";

function loadDraft<T>(callId: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_PREFIX + callId);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function saveDraft(callId: string, data: unknown): void {
  try {
    window.sessionStorage.setItem(STORAGE_PREFIX + callId, JSON.stringify(data));
  } catch {}
}

function clearDraft(callId: string): void {
  try {
    window.sessionStorage.removeItem(STORAGE_PREFIX + callId);
  } catch {}
}

async function submitPendingUserInput(options: {
  toolCallId: string;
  runId?: string | null;
  result: RequestUserInputSubmissionPayload;
}): Promise<UserInputSubmitResult> {
  const normalizedRunId =
    typeof options.runId === "string" && options.runId.trim().length > 0
      ? options.runId.trim()
      : null;
  if (!normalizedRunId) {
    throw new Error("Run context expired. Refresh and try again.");
  }

  const response = await submitRunUserInput({
    runId: normalizedRunId,
    toolCallId: options.toolCallId,
    result: options.result,
  });
  return {
    success: true,
    tool_call_id: options.toolCallId,
    resumed: response.status === "running",
    started_new_run: false,
  };
}

async function cancelPendingRun(runId?: string | null): Promise<void> {
  const normalizedRunId =
    typeof runId === "string" && runId.trim().length > 0
      ? runId.trim()
      : null;
  if (!normalizedRunId) {
    throw new Error("Run context expired. Refresh and try again.");
  }
  await cancelRun(normalizedRunId);
}

// ============================================================================
// UserInputOverlay
// ============================================================================

export const UserInputOverlay: FC<UserInputOverlayProps> = ({
  payload,
  onSubmitted,
}) => {
  const requestPayloads = useMemo(
    () =>
      payload.requests.filter(
        (request): request is RequestUserInputPendingRequestTransport =>
          isComposerInteractiveToolName(request?.toolName) &&
          isRequestUserInputPendingRequestTransport(request),
      ),
    [payload.requests],
  );
  const [pendingRequests, setPendingRequests] = useState<UserInputRequest[]>(requestPayloads);
  const [overlayError, setOverlayError] = useState<string | null>(null);

  useEffect(() => {
    setPendingRequests(requestPayloads);
    setOverlayError(null);
  }, [payload.messageId, requestPayloads]);

  const currentRequest = pendingRequests[0];
  if (!currentRequest) {
    if (!overlayError) return null;
    return (
      <div className="rounded-lg border border-destructive/20 bg-card/80 px-4 py-2">
        <p className="type-size-12 text-destructive">{overlayError}</p>
      </div>
    );
  }

  const handleRequestSubmitted = (response: UserInputSubmitResult, callId: string) => {
    setOverlayError(null);
    const remainingAfterSubmit = pendingRequests.filter((request) => request.callId !== callId);
    setPendingRequests(remainingAfterSubmit);

    if (response.cancelled) {
      onSubmitted();
      return;
    }

    if (response.resumed || response.started_new_run) {
      onSubmitted();
      return;
    }

    if (remainingAfterSubmit.length === 0) {
      setOverlayError("Saved your answers, but the run did not resume automatically.");
    }
  };

  return (
    <QuestionFlow
      key={currentRequest.callId}
      payload={payload}
      request={currentRequest}
      onSubmitted={handleRequestSubmitted}
    />
  );
};

// ============================================================================
// QuestionFlow
// ============================================================================

type QuestionFlowProps = {
  payload: UserInputPayload;
  request: RequestUserInputPendingRequestTransport;
  onSubmitted: (response: UserInputSubmitResult, callId: string) => void;
};

type QuestionDraft = {
  selectedIndexByQuestion: Record<string, number>;
  customByQuestion: Record<string, string>;
  currentIndex: number;
};

const QuestionFlow: FC<QuestionFlowProps> = ({
  payload,
  request,
  onSubmitted,
}) => {
  const requestData = request.request;

  const questions = useMemo(() => {
    const raw = requestData.questions;
    if (!Array.isArray(raw)) return [];
    const normalized: UserInputQuestion[] = [];

    for (const item of raw) {
      if (!item || typeof item !== "object") continue;

      const rawQuestion = item as {
        id?: unknown;
        question?: unknown;
        options?: unknown;
      };
      const id = typeof rawQuestion.id === "string" ? rawQuestion.id.trim() : "";
      const question = typeof rawQuestion.question === "string" ? rawQuestion.question.trim() : "";
      if (!id || !question) continue;
      if (!Array.isArray(rawQuestion.options)) continue;

      const options: UserInputQuestionOption[] = [];
      for (const option of rawQuestion.options) {
        if (!option || typeof option !== "object") continue;
        const rawOption = option as { label?: unknown; description?: unknown };
        const label = typeof rawOption.label === "string" ? rawOption.label.trim() : "";
        const description =
          typeof rawOption.description === "string" ? rawOption.description.trim() : "";
        if (!label || !description) continue;
        options.push({ label, description });
      }

      if (options.length < 2) continue;
      normalized.push({ id, question, options });
    }

    return normalized;
  }, [requestData]);

  const saved = useMemo(() => loadDraft<QuestionDraft>(request.callId), [request.callId]);

  // Default all questions to first option selected
  const defaultSelections = useMemo(() => {
    const map: Record<string, number> = {};
    questions.forEach((q) => {
      map[q.id] = 0;
    });
    return map;
  }, [questions]);

  const [selectedIndexByQuestion, setSelectedIndexByQuestion] = useState<Record<string, number>>(
    () => saved?.selectedIndexByQuestion ?? defaultSelections,
  );
  const [customByQuestion, setCustomByQuestion] = useState<Record<string, string>>(
    saved?.customByQuestion ?? {},
  );
  const [currentIndex, setCurrentIndex] = useState(saved?.currentIndex ?? 0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const otherTextRef = useRef<HTMLTextAreaElement>(null);

  const totalQuestions = questions.length;
  const currentQuestion = questions[currentIndex];
  const isLastQuestion = currentIndex >= totalQuestions - 1;
  // -1 means "Other" is selected
  const highlightedIndex = currentQuestion
    ? (selectedIndexByQuestion[currentQuestion.id] ?? 0)
    : 0;
  const isOtherSelected = highlightedIndex === -1;
  const currentCustomText = currentQuestion ? (customByQuestion[currentQuestion.id] ?? "") : "";

  // Persist draft
  useEffect(() => {
    saveDraft(request.callId, { selectedIndexByQuestion, customByQuestion, currentIndex });
  }, [request.callId, selectedIndexByQuestion, customByQuestion, currentIndex]);

  // ── Submit ────────────────────────────────────────────────────────────────
  const doSubmit = useCallback(async (overrideSelections?: Record<string, number>) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmitError(null);
    setIsSubmitting(true);

    const selections = overrideSelections ?? selectedIndexByQuestion;

    try {
      const answers = questions
        .filter((q) => (selections[q.id] ?? 0) >= 0)
        .map((q) => {
          const idx = selections[q.id] ?? 0;
          const option = q.options[idx];
          return {
            question_id: q.id,
            option_label: option.label,
          };
        });

      // Combine per-question custom responses
      const customParts = Object.entries(customByQuestion)
        .filter(([, text]) => text.trim())
        .map(([qId, text]) => {
          const q = questions.find((item) => item.id === qId);
          return q ? `${q.question}: ${text.trim()}` : text.trim();
        });
      const combinedCustom = customParts.join("\n");

      const response = await submitPendingUserInput({
        toolCallId: request.callId,
        runId: payload.runId,
        result: { answers, custom_response: combinedCustom },
      });
      clearDraft(request.callId);
      onSubmitted(response, request.callId);
    } catch (error) {
      const message =
        error instanceof Error && error.message.trim()
          ? error.message
          : "Unable to submit your input. Please try again.";
      setSubmitError(message);
    } finally {
      submittingRef.current = false;
      setIsSubmitting(false);
    }
  }, [questions, selectedIndexByQuestion, customByQuestion, request.callId, payload.runId, onSubmitted]);

  const dismissPendingInput = useCallback(async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmitError(null);
    setIsSubmitting(true);

    try {
      await cancelPendingRun(payload.runId);
      clearDraft(request.callId);
      onSubmitted(
        {
          success: true,
          tool_call_id: request.callId,
          cancelled: true,
        },
        request.callId,
      );
    } catch (error) {
      const message =
        error instanceof Error && error.message.trim()
          ? error.message
          : "Unable to dismiss this request. Please try again.";
      setSubmitError(message);
    } finally {
      submittingRef.current = false;
      setIsSubmitting(false);
    }
  }, [payload.runId, request.callId, onSubmitted]);

  // ── Navigation ────────────────────────────────────────────────────────────
  const moveOption = useCallback(
    (direction: 1 | -1) => {
      if (!currentQuestion) return;
      setSelectedIndexByQuestion((prev) => {
        const current = prev[currentQuestion.id] ?? 0;
        const maxIdx = currentQuestion.options.length - 1;
        let next: number;
        if (current === -1) {
          next = direction === -1 ? maxIdx : -1;
        } else if (current === maxIdx && direction === 1) {
          next = -1;
        } else {
          next = Math.max(0, Math.min(maxIdx, current + direction));
        }
        return { ...prev, [currentQuestion.id]: next };
      });
    },
    [currentQuestion],
  );

  const goToQuestion = useCallback(
    (index: number) => {
      if (index >= 0 && index < totalQuestions) {
        setCurrentIndex(index);
      }
    },
    [totalQuestions],
  );

  const handleContinue = useCallback(() => {
    if (isLastQuestion) {
      doSubmit();
    } else {
      setCurrentIndex((prev) => prev + 1);
    }
  }, [isLastQuestion, doSubmit]);

  // ── Keyboard ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isSubmitting) return;
      if (isInputFocused(e)) return;

      if (totalQuestions === 0) {
        if (e.key === "Escape") {
          e.preventDefault();
          dismissPendingInput();
        }
        return;
      }

      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          moveOption(-1);
          break;
        case "ArrowDown":
          e.preventDefault();
          moveOption(1);
          break;
        case "ArrowLeft":
          e.preventDefault();
          goToQuestion(currentIndex - 1);
          break;
        case "ArrowRight":
          e.preventDefault();
          goToQuestion(currentIndex + 1);
          break;
        case "Enter":
          e.preventDefault();
          handleContinue();
          break;
        case "Escape":
          e.preventDefault();
          dismissPendingInput();
          break;
        default:
          if (/^[1-9]$/.test(e.key) && currentQuestion) {
            const idx = parseInt(e.key) - 1;
            if (idx < currentQuestion.options.length) {
              e.preventDefault();
              setSelectedIndexByQuestion((prev) => ({
                ...prev,
                [currentQuestion.id]: idx,
              }));
            }
          }
      }
    };

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [
    isSubmitting,
    moveOption,
    goToQuestion,
    handleContinue,
    doSubmit,
    currentIndex,
    currentQuestion,
    dismissPendingInput,
    totalQuestions,
  ]);

  if (totalQuestions === 0) {
    return (
      <div className="flex flex-col rounded-xl border border-emerald-600/25 bg-card/80">
        <div className="px-4 pt-3.5 pb-1.5">
          <MarkdownContent
            content={requestData.title || "assistant needs your input"}
            className="type-size-14 font-medium text-foreground leading-snug"
          />
          <p className="mt-0.5 type-size-12 leading-relaxed text-muted-foreground/70">
            This request format is no longer supported. Dismiss to stop this run.
          </p>
        </div>

        {submitError && (
          <div className="px-4 pb-1">
            <p className="type-size-10 text-destructive">{submitError}</p>
          </div>
        )}

        <div className="flex items-center justify-end px-4 pb-3 pt-1.5">
          <button
            type="button"
            disabled={isSubmitting}
            onClick={dismissPendingInput}
            className="type-size-10 text-muted-foreground/35 transition-colors hover:text-muted-foreground/60 disabled:opacity-50"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  // ── Structured question flow ──────────────────────────────────────────────
  return (
    <div className="flex flex-col rounded-xl border border-emerald-600/25 bg-card/80">
      {/* Question text */}
      <div className="px-4 pt-3.5 pb-2.5">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentQuestion?.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 6 }}
            transition={{ duration: 0.12, ease: [0.25, 0.1, 0.25, 1] }}
          >
            <MarkdownContent
              content={currentQuestion?.question ?? ""}
              className="type-size-14 font-medium text-foreground leading-relaxed"
            />
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Options */}
      <div className="px-1.5">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentQuestion?.id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.1 }}
            className="flex flex-col"
          >
            {currentQuestion?.options.map((option, i) => {
              const isHighlighted = highlightedIndex === i;
              return (
                <button
                  key={`${currentQuestion.id}-${i}`}
                  type="button"
                  disabled={isSubmitting}
                  onClick={() => {
                    const updated = { ...selectedIndexByQuestion, [currentQuestion.id]: i };
                    setSelectedIndexByQuestion(updated);
                    if (isLastQuestion) {
                      setTimeout(() => doSubmit(updated), 150);
                    } else {
                      setTimeout(() => setCurrentIndex((prev) => prev + 1), 150);
                    }
                  }}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-2.5 py-2.5 text-left transition-all duration-100 active:scale-[0.98]",
                    "disabled:cursor-not-allowed disabled:opacity-50",
                    isHighlighted
                      ? "bg-primary/[0.07]"
                      : "hover:bg-muted/30",
                  )}
                >
                  <span
                    className={cn(
                      "shrink-0 w-3 text-right tabular-nums type-size-10 transition-colors",
                      isHighlighted ? "text-primary" : "text-muted-foreground/40",
                    )}
                  >
                    {i + 1}
                  </span>

                  <span
                    className={cn(
                      "type-size-14 font-normal transition-colors",
                      isHighlighted ? "text-foreground" : "text-foreground/80",
                    )}
                  >
                    {option.label}
                  </span>

                  {option.description && (
                    <Tooltip>
                      <TooltipTrigger
                        asChild
                        onClick={(e) => e.stopPropagation()}
                      >
                        <span className="inline-flex items-center">
                          <Info className="h-3 w-3 text-muted-foreground/40" />
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-64">
                        {option.description}
                      </TooltipContent>
                    </Tooltip>
                  )}
                </button>
              );
            })}

            {/* Other — inline auto-growing input */}
            {currentQuestion && (
              <div
                onClick={() => {
                  if (!isSubmitting) {
                    setSelectedIndexByQuestion((prev) => ({
                      ...prev,
                      [currentQuestion.id]: -1,
                    }));
                    otherTextRef.current?.focus();
                  }
                }}
                className={cn(
                  "flex items-baseline gap-2 rounded-md px-2.5 py-2.5 transition-all duration-100 cursor-text",
                  isOtherSelected ? "bg-primary/[0.07]" : "hover:bg-muted/30",
                )}
              >
                <span
                  className={cn(
                    "shrink-0 w-3 text-right tabular-nums type-size-10 transition-colors",
                    isOtherSelected ? "text-primary" : "text-muted-foreground/40",
                  )}
                >
                  {currentQuestion.options.length + 1}
                </span>
                <textarea
                  ref={otherTextRef}
                  value={currentCustomText}
                  onChange={(e) => {
                    setSubmitError(null);
                    if (currentQuestion) {
                      setCustomByQuestion((prev) => ({
                        ...prev,
                        [currentQuestion.id]: e.target.value,
                      }));
                    }
                    const el = e.target;
                    el.style.height = "auto";
                    el.style.height = `${el.scrollHeight}px`;
                  }}
                  onFocus={() => {
                    if (currentQuestion) {
                      setSelectedIndexByQuestion((prev) => ({
                        ...prev,
                        [currentQuestion.id]: -1,
                      }));
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && currentCustomText.trim() && !isSubmitting) {
                      e.preventDefault();
                      handleContinue();
                    }
                    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && !currentCustomText.trim()) {
                      e.preventDefault();
                    }
                  }}
                  disabled={isSubmitting}
                  placeholder="Tell assistant what to do differently"
                  rows={1}
                  className="min-w-0 flex-1 resize-none overflow-hidden bg-transparent type-chat-input text-muted-foreground/40 placeholder:text-muted-foreground/40 focus:text-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {submitError && (
        <div className="px-4 pb-1">
          <p className="type-size-10 text-destructive">{submitError}</p>
        </div>
      )}

      {/* Bottom bar: dots + dismiss + optional submit */}
      <div className="flex items-center px-4 pb-3 pt-1.5">
        {totalQuestions > 1 && (
          <div className="flex items-center gap-1">
            {questions.map((_, i) => (
              <button
                key={i}
                type="button"
                disabled={isSubmitting}
                onClick={() => goToQuestion(i)}
                className={cn(
                  "rounded-full transition-all duration-200",
                  i === currentIndex
                    ? "h-1.5 w-3.5 bg-primary/50"
                    : "h-1.5 w-1.5 bg-muted-foreground/15 hover:bg-muted-foreground/30",
                )}
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-2.5 ml-auto">
          <button
            type="button"
            disabled={isSubmitting}
            onClick={dismissPendingInput}
            className="type-size-10 text-muted-foreground/35 transition-colors hover:text-muted-foreground/60 disabled:opacity-50"
          >
            Dismiss
          </button>
          {isOtherSelected && currentCustomText.trim() && (
            <Button
              type="button"
              size="sm"
              disabled={isSubmitting}
              onClick={handleContinue}
              className="h-6 px-3 type-size-10 rounded-lg"
            >
              {isSubmitting && <SpinnerGap className="h-3 w-3 animate-spin" />}
              {isLastQuestion ? (requestData.submit_label || "Submit") : "Continue"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
