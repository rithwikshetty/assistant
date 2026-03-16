function pickErrorMessage(payload: unknown): string | null {
  if (payload == null) return null;
  if (typeof payload === "string") {
    const message = payload.trim();
    return message.length > 0 ? message : null;
  }
  if (Array.isArray(payload)) {
    for (const item of payload) {
      const nested = pickErrorMessage(item);
      if (nested) return nested;
    }
    return null;
  }
  if (typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    for (const key of ["detail", "message", "error", "reason", "msg"]) {
      const nested = pickErrorMessage(record[key]);
      if (nested) return nested;
    }
    for (const value of Object.values(record)) {
      const nested = pickErrorMessage(value);
      if (nested) return nested;
    }
  }
  return null;
}

export async function readApiErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const text = (await response.text()).trim();
    if (text) {
      try {
        const data = JSON.parse(text) as unknown;
        const message = pickErrorMessage(data);
        if (message) return message;
      } catch {
        return text;
      }
    }
  } catch {}

  return `${fallback} (${response.status})`;
}

export async function parseApiError(response: Response, fallback: string): Promise<never> {
  throw new Error(await readApiErrorMessage(response, fallback));
}
