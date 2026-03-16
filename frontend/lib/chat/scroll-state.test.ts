import { describe, expect, it } from "vitest";

import {
  deriveViewportScrollState,
  resolveInitialScrollDecision,
  shouldPreservePinnedBottomOnScroll,
} from "@/lib/chat/scroll-state";

describe("scroll-state", () => {
  describe("deriveViewportScrollState", () => {
    it("keeps user pinned when content grows and preserve mode is enabled", () => {
      const result = deriveViewportScrollState({
        scrollTop: 500,
        scrollHeight: 1450,
        clientHeight: 700,
        wasUserAtBottom: true,
        preservePinnedBottom: true,
      });

      expect(result.isUserAtBottom).toBe(true);
      expect(result.showScrollToBottom).toBe(false);
    });

    it("releases bottom pin when preserve mode is disabled", () => {
      const result = deriveViewportScrollState({
        scrollTop: 500,
        scrollHeight: 1450,
        clientHeight: 700,
        wasUserAtBottom: true,
        preservePinnedBottom: false,
      });

      expect(result.isUserAtBottom).toBe(false);
      expect(result.showScrollToBottom).toBe(true);
    });

    it("treats near-bottom positions as pinned", () => {
      const result = deriveViewportScrollState({
        scrollTop: 598,
        scrollHeight: 1200,
        clientHeight: 600,
        wasUserAtBottom: false,
        preservePinnedBottom: false,
      });

      expect(result.distanceFromBottom).toBe(2);
      expect(result.isUserAtBottom).toBe(true);
      expect(result.showScrollToBottom).toBe(false);
    });

    it("shows the button once distance crosses the configured threshold", () => {
      const hiddenAtThreshold = deriveViewportScrollState({
        scrollTop: 280,
        scrollHeight: 1000,
        clientHeight: 600,
        wasUserAtBottom: false,
        preservePinnedBottom: false,
      });
      const shownPastThreshold = deriveViewportScrollState({
        scrollTop: 279,
        scrollHeight: 1000,
        clientHeight: 600,
        wasUserAtBottom: false,
        preservePinnedBottom: false,
      });

      expect(hiddenAtThreshold.distanceFromBottom).toBe(120);
      expect(hiddenAtThreshold.showScrollToBottom).toBe(false);
      expect(shownPastThreshold.distanceFromBottom).toBe(121);
      expect(shownPastThreshold.showScrollToBottom).toBe(true);
    });
  });

  describe("resolveInitialScrollDecision", () => {
    it("re-arms initial scroll when conversation changes", () => {
      const decision = resolveInitialScrollDecision({
        conversationId: "conv_b",
        trackedConversationId: "conv_a",
        hasScrolledOnLoad: true,
        isLoadingInitial: false,
        timelineLength: 3,
      });

      expect(decision.shouldScrollNow).toBe(true);
      expect(decision.nextHasScrolledOnLoad).toBe(true);
      expect(decision.nextConversationId).toBe("conv_b");
    });

    it("does not rerun initial scroll after it already fired for same conversation", () => {
      const decision = resolveInitialScrollDecision({
        conversationId: "conv_a",
        trackedConversationId: "conv_a",
        hasScrolledOnLoad: true,
        isLoadingInitial: false,
        timelineLength: 3,
      });

      expect(decision.shouldScrollNow).toBe(false);
      expect(decision.nextHasScrolledOnLoad).toBe(true);
    });

    it("waits for initial load completion", () => {
      const decision = resolveInitialScrollDecision({
        conversationId: "conv_a",
        trackedConversationId: "conv_a",
        hasScrolledOnLoad: false,
        isLoadingInitial: true,
        timelineLength: 3,
      });

      expect(decision.shouldScrollNow).toBe(false);
      expect(decision.nextHasScrolledOnLoad).toBe(false);
    });
  });

  describe("shouldPreservePinnedBottomOnScroll", () => {
    it("preserves pin for neutral/downward movement when auto-follow is enabled", () => {
      expect(
        shouldPreservePinnedBottomOnScroll({
          autoFollowEnabled: true,
          previousScrollTop: 500,
          currentScrollTop: 500,
        }),
      ).toBe(true);
      expect(
        shouldPreservePinnedBottomOnScroll({
          autoFollowEnabled: true,
          previousScrollTop: 500,
          currentScrollTop: 520,
        }),
      ).toBe(true);
    });

    it("releases pin for upward movement or disabled auto-follow", () => {
      expect(
        shouldPreservePinnedBottomOnScroll({
          autoFollowEnabled: true,
          previousScrollTop: 500,
          currentScrollTop: 497,
        }),
      ).toBe(false);
      expect(
        shouldPreservePinnedBottomOnScroll({
          autoFollowEnabled: false,
          previousScrollTop: 500,
          currentScrollTop: 500,
        }),
      ).toBe(false);
    });
  });
});
