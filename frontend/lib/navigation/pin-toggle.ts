type Pinnable = {
  is_pinned?: boolean;
  pinned_at?: string | null;
};

type PinServerFields = {
  is_pinned?: boolean;
  pinned_at?: string | null;
  updated_at: string;
  last_message_at: string;
};

type PinToast = {
  type?: "success" | "error" | "info";
  title: string;
  description?: string;
};

export function applyOptimisticPinToggle<T extends Pinnable>(current: T, nowIso: string): T {
  const willBePinned = !Boolean(current.is_pinned);
  return {
    ...current,
    is_pinned: willBePinned,
    pinned_at: willBePinned ? nowIso : null,
  };
}

export function rollbackOptimisticPinToggle<T extends Pinnable>(current: T, previous?: T | null): T {
  if (previous) return previous;
  const wasPinned = Boolean(current.is_pinned);
  return {
    ...current,
    is_pinned: !wasPinned,
    pinned_at: wasPinned ? null : (current.pinned_at ?? null),
  };
}

export function mergeServerPinFields<T extends Pinnable & { updated_at: string; last_message_at: string }>(
  current: T,
  server: PinServerFields,
): T {
  return {
    ...current,
    is_pinned: Boolean(server.is_pinned),
    pinned_at: server.pinned_at ?? null,
    updated_at: server.updated_at,
    last_message_at: server.last_message_at,
  };
}

/**
 * Orchestrate optimistic pin toggle with rollback on failure.
 *
 * Handles snapshot capture, optimistic update, API call, server merge,
 * rollback, error toast, and operating-state cleanup.
 */
export function performPinToggle<T extends Pinnable & { id: string; updated_at: string; last_message_at: string }>(opts: {
  conversationId: string;
  updateItems: (updater: (current: T[]) => T[]) => void;
  apiCall: (conversationId: string) => Promise<PinServerFields>;
  setOperatingId: (id: string | null) => void;
  addToast: (toast: PinToast) => void;
}): void {
  const { conversationId, updateItems, apiCall, setOperatingId, addToast } = opts;

  setOperatingId(conversationId);
  const nowIso = new Date().toISOString();
  let snapshot: T | undefined;

  updateItems((current) =>
    current.map((c) => {
      if (c.id !== conversationId) return c;
      snapshot = c;
      return applyOptimisticPinToggle(c, nowIso);
    }),
  );

  (async () => {
    try {
      const updated = await apiCall(conversationId);
      updateItems((current) =>
        current.map((c) => (c.id === conversationId ? mergeServerPinFields(c, updated) : c)),
      );
    } catch (error) {
      updateItems((current) =>
        current.map((c) => (c.id === conversationId ? rollbackOptimisticPinToggle(c, snapshot) : c)),
      );
      addToast({
        type: "error",
        title: "Couldn't update pin",
        description: error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      setOperatingId(null);
    }
  })();
}
