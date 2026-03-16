export type WebShareData = {
  url: string;
  title?: string;
  text?: string;
};

export function canUseWebShare(): boolean {
  return typeof navigator !== "undefined" && "share" in navigator && typeof navigator.share === "function";
}

export async function tryWebShare(data: WebShareData): Promise<boolean> {
  try {
    if (!canUseWebShare()) return false;
    // Some browsers reject when empty strings are passed
    const payload: Record<string, string> = { url: data.url };
    if (data.title) payload.title = data.title;
    if (data.text) payload.text = data.text;
    if ("share" in navigator && navigator.share) {
      await navigator.share(payload);
    }
    return true;
  } catch {
    return false;
  }
}

export function canUseClipboard(): boolean {
  return typeof navigator !== "undefined" && !!navigator.clipboard && typeof navigator.clipboard.writeText === "function";
}

export async function tryClipboardWrite(text: string): Promise<boolean> {
  try {
    if (!canUseClipboard()) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

