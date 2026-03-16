/**
 * Local development uses the Vite dev server as the stable browser origin and
 * proxies backend routes through it, so the frontend never hard-codes a backend
 * port.
 */
export function getBackendBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin.replace(/\/+$/, "");
  }
  return "http://localhost";
}
