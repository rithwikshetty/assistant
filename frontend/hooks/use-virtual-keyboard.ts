/**
 * useVirtualKeyboard — tracks virtual keyboard height on mobile devices.
 *
 * Uses the `visualViewport` API (iOS 13+, Android Chrome 61+) to detect
 * when the software keyboard is open and calculate its height.
 *
 * Smart about `interactive-widget=resizes-content`: when the browser natively
 * resizes the layout viewport for the keyboard, `window.innerHeight` already
 * tracks the change and `keyboardHeight` stays at 0 (no double-shrink).
 * When the browser does NOT natively resize (older iOS, Firefox), this hook
 * detects the gap between the layout viewport and visual viewport and reports
 * the keyboard height for manual adjustment.
 *
 * Also sets `--keyboard-height` on <html> for CSS-based adjustments.
 */

import { useEffect, useRef, useState, useCallback } from "react";

/** Minimum height delta to consider the keyboard "open" (px). */
const KEYBOARD_THRESHOLD = 100;

/** Debounce interval for viewport resize events (ms). */
const RESIZE_DEBOUNCE_MS = 60;

export type VirtualKeyboardState = {
  /** Pixels the keyboard consumes that the layout viewport doesn't account for. */
  keyboardHeight: number;
  /** True when a virtual keyboard is detected (regardless of whether the layout viewport resized). */
  isKeyboardOpen: boolean;
};

const IDLE_STATE: VirtualKeyboardState = { keyboardHeight: 0, isKeyboardOpen: false };

export function useVirtualKeyboard(enabled = true): VirtualKeyboardState {
  const [state, setState] = useState<VirtualKeyboardState>(IDLE_STATE);

  const rafRef = useRef(0);
  const debounceTimerRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Store the initial full height for keyboard-open detection (even when
  // the browser natively resizes).
  const initialHeightRef = useRef(
    typeof window !== "undefined" ? window.innerHeight : 0
  );

  const update = useCallback(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    const visualHeight = vv.height;
    const layoutHeight = window.innerHeight;

    // Detect whether a keyboard is open at all, using initial height baseline.
    // This works regardless of interactive-widget support.
    const initialHeight = initialHeightRef.current;
    const isOpen = initialHeight - visualHeight > KEYBOARD_THRESHOLD;

    // The "unaccounted" height is the gap between the layout viewport and the
    // visual viewport. If the browser natively resizes the layout (via
    // interactive-widget=resizes-content or Android default), this gap is ~0.
    // If it doesn't, this is the keyboard height we need to compensate for.
    const unaccounted = Math.max(0, Math.round(layoutHeight - visualHeight));
    const effectiveHeight = unaccounted > KEYBOARD_THRESHOLD ? unaccounted : 0;

    const prev = stateRef.current;
    if (prev.keyboardHeight === effectiveHeight && prev.isKeyboardOpen === isOpen) {
      return; // No change.
    }

    setState({ keyboardHeight: effectiveHeight, isKeyboardOpen: isOpen });
    document.documentElement.style.setProperty(
      "--keyboard-height",
      `${effectiveHeight}px`
    );
  }, []);

  useEffect(() => {
    if (!enabled) {
      // Reset state and CSS variable when disabled.
      if (stateRef.current.keyboardHeight !== 0 || stateRef.current.isKeyboardOpen) {
        setState(IDLE_STATE);
        document.documentElement.style.removeProperty("--keyboard-height");
      }
      return;
    }

    const vv = window.visualViewport;
    if (!vv) return;

    initialHeightRef.current = window.innerHeight;

    const handleResize = () => {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = window.setTimeout(() => {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(update);
      }, RESIZE_DEBOUNCE_MS);
    };

    const handleOrientationChange = () => {
      setTimeout(() => {
        initialHeightRef.current = window.innerHeight;
        update();
      }, 350);
    };

    // iOS sometimes doesn't fire visualViewport resize when tapping between
    // inputs of the same size. Focus events cover this gap.
    const handleFocusIn = () => setTimeout(handleResize, 120);
    const handleFocusOut = () => setTimeout(handleResize, 200);

    vv.addEventListener("resize", handleResize);
    vv.addEventListener("scroll", handleResize);
    window.addEventListener("orientationchange", handleOrientationChange);
    document.addEventListener("focusin", handleFocusIn);
    document.addEventListener("focusout", handleFocusOut);

    return () => {
      vv.removeEventListener("resize", handleResize);
      vv.removeEventListener("scroll", handleResize);
      window.removeEventListener("orientationchange", handleOrientationChange);
      document.removeEventListener("focusin", handleFocusIn);
      document.removeEventListener("focusout", handleFocusOut);
      clearTimeout(debounceTimerRef.current);
      cancelAnimationFrame(rafRef.current);
      document.documentElement.style.removeProperty("--keyboard-height");
    };
  }, [enabled, update]);

  return state;
}
