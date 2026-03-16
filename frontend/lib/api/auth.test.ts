import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();
const getBackendTokenMock = vi.fn();
const clearBackendTokenMock = vi.fn();

vi.mock("@/lib/utils/backend-url", () => ({
  getBackendBaseUrl: () => "http://assist.test",
}));

vi.mock("@/lib/utils/cookie-manager", () => ({
  setBackendToken: vi.fn(),
  getBackendToken: () => getBackendTokenMock(),
  clearBackendToken: () => clearBackendTokenMock(),
  setRefreshToken: vi.fn(),
  getRefreshToken: vi.fn(),
  clearAllTokens: vi.fn(),
}));

describe("getUserConversations", () => {
  beforeEach(() => {
    vi.resetModules();
    fetchMock.mockReset();
    getBackendTokenMock.mockReset();
    clearBackendTokenMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    getBackendTokenMock.mockReturnValue("session-token");
  });

  it("throws a typed API error instead of collapsing to an empty list on server failure", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Database unavailable", code: "DB_DOWN" }), {
        status: 503,
        headers: {
          "content-type": "application/json",
          "retry-after": "12",
        },
      }),
    );

    const { getUserConversations } = await import("./auth");

    await expect(getUserConversations()).rejects.toMatchObject({
      message: "Database unavailable",
      status: 503,
      code: "DB_DOWN",
      detail: "Database unavailable",
      retryAfterSeconds: 12,
    });
  });

  it("still clears auth and returns an empty list on 401", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }));

    const { getUserConversations } = await import("./auth");

    await expect(getUserConversations()).resolves.toEqual([]);
    expect(clearBackendTokenMock).toHaveBeenCalledTimes(1);
  });
});
