import { describe, expect, it } from "vitest";

import { readApiErrorMessage } from "./errors";

describe("readApiErrorMessage", () => {
  it("returns detail from JSON payloads", async () => {
    const response = new Response(JSON.stringify({ detail: "Database unavailable" }), {
      status: 503,
      headers: { "content-type": "application/json" },
    });

    await expect(readApiErrorMessage(response, "Fallback")).resolves.toBe("Database unavailable");
  });

  it("returns message from JSON payloads", async () => {
    const response = new Response(JSON.stringify({ message: "Access denied" }), {
      status: 403,
      headers: { "content-type": "application/json" },
    });

    await expect(readApiErrorMessage(response, "Fallback")).resolves.toBe("Access denied");
  });

  it("falls back to plain text responses", async () => {
    const response = new Response("Gateway timeout", { status: 504 });

    await expect(readApiErrorMessage(response, "Fallback")).resolves.toBe("Gateway timeout");
  });

  it("uses the fallback when the payload has no readable message", async () => {
    const response = new Response(JSON.stringify({ ok: false }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });

    await expect(readApiErrorMessage(response, "Fallback")).resolves.toBe("Fallback (500)");
  });
});
