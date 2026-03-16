/**
 * Local workspace marker storage.
 */

const LOCAL_SESSION_FALLBACK = "local-workspace-session";

const COOKIE_NAME = 'backend_session_token';
const REFRESH_TOKEN_COOKIE_NAME = 'backend_refresh_token';
const COOKIE_MAX_AGE = 60 * 60 * 24 * 7; // 7 days in seconds

/**
 * Set a cookie (client-side)
 */
function setCookie(name: string, value: string, maxAge: number = COOKIE_MAX_AGE): void {
  if (typeof window === 'undefined') return;
  
  const expires = new Date();
  expires.setTime(expires.getTime() + (maxAge * 1000));
  
  document.cookie = `${name}=${value}; path=/; expires=${expires.toUTCString()}; SameSite=Lax`;
}

/**
 * Get a cookie (client-side)
 */
function getCookie(name: string): string | null {
  if (typeof window === 'undefined') return null;
  
  const cookies = document.cookie.split(';');
  for (const cookie of cookies) {
    const [cookieName, cookieValue] = cookie.trim().split('=');
    if (cookieName === name) {
      return cookieValue;
    }
  }
  return null;
}

/**
 * Delete a cookie (client-side)
 */
function deleteCookie(name: string): void {
  if (typeof window === 'undefined') return;
  
  document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax`;
}

/**
 * Set the backend session token in the cookie store.
 */
export function setBackendToken(token: string): void {
  if (typeof window === 'undefined') return;
  setCookie(COOKIE_NAME, token);
}

/**
 * Get the backend session token from the cookie store.
 */
export function getBackendToken(): string | null {
  if (typeof window === 'undefined') return null;
  return getCookie(COOKIE_NAME) || LOCAL_SESSION_FALLBACK;
}

/**
 * Clear the backend session token.
 */
export function clearBackendToken(): void {
  if (typeof window === 'undefined') return;

  deleteCookie(COOKIE_NAME);
}

/**
 * Set the refresh token in the cookie store.
 */
export function setRefreshToken(token: string): void {
  if (typeof window === 'undefined') return;

  setCookie(REFRESH_TOKEN_COOKIE_NAME, token);
}

/**
 * Get the refresh token from the cookie store.
 */
export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return getCookie(REFRESH_TOKEN_COOKIE_NAME) || LOCAL_SESSION_FALLBACK;
}

/**
 * Clear the refresh token.
 */
function clearRefreshToken(): void {
  if (typeof window === 'undefined') return;

  deleteCookie(REFRESH_TOKEN_COOKIE_NAME);
}

/**
 * Clear all local session markers.
 */
export function clearAllTokens(): void {
  clearBackendToken();
  clearRefreshToken();
}
