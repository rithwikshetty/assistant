// Shared chart colour helpers — Warm Obsidian palette.

export const BRAND_COLORS = {
  BURNT_ORANGE: "#C2410C",
  WARM_CREAM: "#FAF9F7",
  CHARCOAL: "#1C1917",
  TEAL: "#0D9488",
  AMBER: "#D97706",
  VIOLET: "#7C3AED",
} as const;

import { lightenColor } from "@/lib/color";

export function makeTints(base: string, steps: number[] = [0, 0.15, 0.3, 0.45, 0.6]): string[] {
  return steps
    .map((s) => lightenColor(base, s) || base)
    .filter((c, idx, arr) => arr.indexOf(c) === idx);
}

export function categoricalPalette(): string[] {
  const { BURNT_ORANGE, TEAL, VIOLET, AMBER, CHARCOAL } = BRAND_COLORS;
  return [
    BURNT_ORANGE,
    TEAL,
    VIOLET,
    AMBER,
    ...makeTints(BURNT_ORANGE, [0.2, 0.35, 0.5]),
    ...makeTints(TEAL, [0.2, 0.35, 0.5]),
    ...makeTints(VIOLET, [0.2, 0.35, 0.5]),
    ...makeTints(CHARCOAL, [0.65, 0.8]),
  ];
}

export function savedPiePalette(): string[] {
  return makeTints(BRAND_COLORS.TEAL, [0, 0.15, 0.3, 0.45, 0.6, 0.75]);
}

export function lostPiePalette(): string[] {
  return makeTints(BRAND_COLORS.BURNT_ORANGE, [0, 0.15, 0.3, 0.45, 0.6, 0.75]);
}
