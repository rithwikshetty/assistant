export const SCROLL_BOTTOM_EPSILON_PX = 2;
export const SCROLL_TO_BOTTOM_BUTTON_THRESHOLD_PX = 120;

export type ViewportScrollStateArgs = {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  wasUserAtBottom: boolean;
  preservePinnedBottom?: boolean;
};

export type ViewportScrollState = {
  isUserAtBottom: boolean;
  showScrollToBottom: boolean;
  distanceFromBottom: number;
};

export type PreservePinnedBottomOnScrollArgs = {
  autoFollowEnabled: boolean;
  previousScrollTop: number;
  currentScrollTop: number;
};

export function deriveViewportScrollState(args: ViewportScrollStateArgs): ViewportScrollState {
  const maxScrollTop = Math.max(0, args.scrollHeight - args.clientHeight);
  const distanceFromBottom = maxScrollTop - args.scrollTop;
  const isAtBottomNow = distanceFromBottom <= SCROLL_BOTTOM_EPSILON_PX;
  const keepPinnedAtBottom = Boolean(args.preservePinnedBottom && args.wasUserAtBottom && !isAtBottomNow);
  const isUserAtBottom = isAtBottomNow || keepPinnedAtBottom;
  const showScrollToBottom = !isUserAtBottom && distanceFromBottom > SCROLL_TO_BOTTOM_BUTTON_THRESHOLD_PX;

  return {
    isUserAtBottom,
    showScrollToBottom,
    distanceFromBottom,
  };
}

export function shouldPreservePinnedBottomOnScroll(
  args: PreservePinnedBottomOnScrollArgs,
): boolean {
  if (!args.autoFollowEnabled) {
    return false;
  }

  // Preserve bottom pin for layout/content growth and neutral/downward movement.
  // If user moved upward, release pin so manual scroll-up always wins.
  return args.currentScrollTop >= args.previousScrollTop - 1;
}

export type InitialScrollDecisionArgs = {
  conversationId: string;
  trackedConversationId: string | null;
  hasScrolledOnLoad: boolean;
  isLoadingInitial: boolean;
  timelineLength: number;
};

export type InitialScrollDecision = {
  shouldScrollNow: boolean;
  nextConversationId: string;
  nextHasScrolledOnLoad: boolean;
};

export function resolveInitialScrollDecision(args: InitialScrollDecisionArgs): InitialScrollDecision {
  const conversationChanged = args.trackedConversationId !== args.conversationId;
  const hasScrolledForConversation = conversationChanged ? false : args.hasScrolledOnLoad;
  const shouldScrollNow = !args.isLoadingInitial && args.timelineLength > 0 && !hasScrolledForConversation;

  return {
    shouldScrollNow,
    nextConversationId: args.conversationId,
    nextHasScrolledOnLoad: hasScrolledForConversation || shouldScrollNow,
  };
}
