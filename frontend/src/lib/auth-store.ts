/**
 * The single source of truth for the access token.
 *
 * Persisted in localStorage so a reload keeps the session, with an in-memory
 * cache so reads don't hit storage on every request. `client.ts` reads the
 * token to authorize requests; pages set it on login and clear it on logout.
 */
const STORAGE_KEY = "gold.access_token";

let cached: string | null = null;
let loaded = false;

function read(): string | null {
  if (!loaded) {
    cached = localStorage.getItem(STORAGE_KEY);
    loaded = true;
  }
  return cached;
}

export const authStore = {
  getToken(): string | null {
    return read();
  },
  setToken(token: string): void {
    cached = token;
    loaded = true;
    localStorage.setItem(STORAGE_KEY, token);
  },
  clearToken(): void {
    cached = null;
    loaded = true;
    localStorage.removeItem(STORAGE_KEY);
  },
};
