import { describe, expect, it, vi } from "vitest";

import {
  applyOptimisticPinToggle,
  rollbackOptimisticPinToggle,
  mergeServerPinFields,
  performPinToggle,
} from "./pin-toggle";

describe("pin-toggle helpers", () => {
  it("pins with current timestamp when optimistically toggled from unpinned", () => {
    const base = { id: "c1", is_pinned: false, pinned_at: null };
    const next = applyOptimisticPinToggle(base, "2026-03-03T00:00:00.000Z");
    expect(next.is_pinned).toBe(true);
    expect(next.pinned_at).toBe("2026-03-03T00:00:00.000Z");
  });

  it("unpins when optimistically toggled from pinned", () => {
    const base = { id: "c1", is_pinned: true, pinned_at: "2026-03-02T20:00:00.000Z" };
    const next = applyOptimisticPinToggle(base, "2026-03-03T00:00:00.000Z");
    expect(next.is_pinned).toBe(false);
    expect(next.pinned_at).toBeNull();
  });

  it("restores exact previous snapshot on rollback", () => {
    const previous: { id: string; is_pinned: boolean; pinned_at: string | null } = {
      id: "c1",
      is_pinned: true,
      pinned_at: "2026-03-02T20:00:00.000Z",
    };
    const optimistic: { id: string; is_pinned: boolean; pinned_at: string | null } = {
      id: "c1",
      is_pinned: false,
      pinned_at: null,
    };
    const restored = rollbackOptimisticPinToggle(optimistic, previous);
    expect(restored).toEqual(previous);
  });

  it("merges server pin fields onto existing item", () => {
    const current = { id: "c1", is_pinned: false, pinned_at: null, updated_at: "old", last_message_at: "old", title: "kept" };
    const server = { is_pinned: true, pinned_at: "2026-03-03T00:00:00.000Z", updated_at: "new", last_message_at: "new" };
    const merged = mergeServerPinFields(current, server);
    expect(merged.is_pinned).toBe(true);
    expect(merged.pinned_at).toBe("2026-03-03T00:00:00.000Z");
    expect(merged.updated_at).toBe("new");
    expect(merged.last_message_at).toBe("new");
    expect((merged as typeof current).title).toBe("kept");
  });

  it("performPinToggle applies optimistic update then merges server response", async () => {
    type Item = { id: string; is_pinned: boolean; pinned_at: string | null; updated_at: string; last_message_at: string };
    let items: Item[] = [{ id: "c1", is_pinned: false, pinned_at: null, updated_at: "t0", last_message_at: "t0" }];
    const updateItems = (fn: (c: Item[]) => Item[]) => { items = fn(items); };
    const setOperatingId = vi.fn();
    const addToast = vi.fn();
    const apiCall = vi.fn().mockResolvedValue({
      is_pinned: true, pinned_at: "2026-03-03T01:00:00.000Z", updated_at: "t1", last_message_at: "t1",
    });

    performPinToggle({ conversationId: "c1", updateItems, apiCall, setOperatingId, addToast });

    // After synchronous part: optimistic update applied
    expect(items[0].is_pinned).toBe(true);
    expect(setOperatingId).toHaveBeenCalledWith("c1");

    // Wait for async resolution
    await vi.waitFor(() => expect(apiCall).toHaveBeenCalled());
    await vi.waitFor(() => expect(setOperatingId).toHaveBeenCalledWith(null));
    expect(items[0].updated_at).toBe("t1");
    expect(addToast).not.toHaveBeenCalled();
  });

  it("performPinToggle rolls back on API failure", async () => {
    type Item = { id: string; is_pinned: boolean; pinned_at: string | null; updated_at: string; last_message_at: string };
    let items: Item[] = [{ id: "c1", is_pinned: true, pinned_at: "2026-03-02T00:00:00.000Z", updated_at: "t0", last_message_at: "t0" }];
    const updateItems = (fn: (c: Item[]) => Item[]) => { items = fn(items); };
    const setOperatingId = vi.fn();
    const addToast = vi.fn();
    const apiCall = vi.fn().mockRejectedValue(new Error("Network error"));

    performPinToggle({ conversationId: "c1", updateItems, apiCall, setOperatingId, addToast });

    // Optimistic: toggled to unpinned
    expect(items[0].is_pinned).toBe(false);

    await vi.waitFor(() => expect(setOperatingId).toHaveBeenCalledWith(null));
    // Rolled back to original
    expect(items[0].is_pinned).toBe(true);
    expect(items[0].pinned_at).toBe("2026-03-02T00:00:00.000Z");
    expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: "error" }));
  });
});
