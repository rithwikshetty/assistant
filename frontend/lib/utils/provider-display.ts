// Keep provider colors aligned with the app chart palette.
const DEFAULT_MODEL_COLOR = "var(--chart-5)"; // Neutral

const MODEL_COLOR_MAP: Record<string, string> = {
  "gpt-5.4": "var(--chart-3)", // OpenAI GPT-5.4
  openai: "var(--chart-3)",
};

export function formatModelName(rawModel: string | null | undefined): string {
  if (!rawModel) return "Unknown";
  const normalized = rawModel.toLowerCase();
  if (normalized === "gpt-5.4" || normalized.startsWith("gpt-5.4")) return "GPT-5.4";
  if (normalized === "other") return "Other";
  if (normalized === "openai") return "OpenAI";

  return (
    rawModel
      .split(/[-_]/)
      .filter(Boolean)
      .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
      .join(" ") || "Unknown"
  );
}

export function getModelColor(rawModel: string | null | undefined): string {
  if (!rawModel) return DEFAULT_MODEL_COLOR;
  const normalized = rawModel.toLowerCase();
  if (MODEL_COLOR_MAP[normalized]) return MODEL_COLOR_MAP[normalized];
  return MODEL_COLOR_MAP[normalized] ?? DEFAULT_MODEL_COLOR;
}

export const KNOWN_MODEL_KEYS = ["gpt-5.4"];
