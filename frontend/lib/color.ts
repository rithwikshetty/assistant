export function normalizeHex(color: string | null | undefined): string | null {
  if (!color) return null;
  const trimmed = color.trim();
  if (!/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(trimmed)) {
    return null;
  }
  if (trimmed.length === 4) {
    const r = trimmed[1];
    const g = trimmed[2];
    const b = trimmed[3];
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return trimmed.toLowerCase();
}

/**
 * Lighten a hex colour by blending it with white.
 * @param color Source colour in hex format (#rgb or #rrggbb).
 * @param amount Blend factor between 0 (no change) and 1 (fully white).
 */
export function lightenColor(color: string | null | undefined, amount: number): string | null {
  const normalized = normalizeHex(color);
  if (!normalized) return null;
  const weight = Math.min(Math.max(amount, 0), 1);
  const r = parseInt(normalized.slice(1, 3), 16);
  const g = parseInt(normalized.slice(3, 5), 16);
  const b = parseInt(normalized.slice(5, 7), 16);

  const lightenComponent = (component: number) => {
    const value = Math.round(component + (255 - component) * weight);
    return value.toString(16).padStart(2, "0");
  };

  return `#${lightenComponent(r)}${lightenComponent(g)}${lightenComponent(b)}`;
}

/**
 * Darken a hex colour by blending it with black.
 */
export function darkenColor(color: string | null | undefined, amount: number): string | null {
  const normalized = normalizeHex(color);
  if (!normalized) return null;
  const weight = Math.min(Math.max(amount, 0), 1);
  const r = parseInt(normalized.slice(1, 3), 16);
  const g = parseInt(normalized.slice(3, 5), 16);
  const b = parseInt(normalized.slice(5, 7), 16);

  const darkenComponent = (component: number) => {
    const value = Math.round(component * (1 - weight));
    return value.toString(16).padStart(2, "0");
  };

  return `#${darkenComponent(r)}${darkenComponent(g)}${darkenComponent(b)}`;
}

/**
 * Apply transparency to a hex colour, returning an rgba string.
 */
export function withAlpha(color: string | null | undefined, alpha: number): string | null {
  const normalized = normalizeHex(color);
  if (!normalized) return null;
  const a = Math.min(Math.max(alpha, 0), 1);
  const r = parseInt(normalized.slice(1, 3), 16);
  const g = parseInt(normalized.slice(3, 5), 16);
  const b = parseInt(normalized.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}
