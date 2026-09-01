import { useSyncExternalStore } from "react";

/**
 * The single source of truth for the access token.
 *
 * Persisted in localStorage so a reload keeps the session, with an in-memory
 * cache so reads don't hit storage on every request. `client.ts` reads the
 * token to authorize requests; route guards read it through the router context;
 * pages set it on login and clear it on logout.
 *
 * It is also an external store: React can subscribe to it, so the header
 * reflects a login or a logout the moment it happens.
 */
const STORAGE_KEY = "gold.access_token";

let cached: string | null = null;
let loaded = false;

const listeners = new Set<() => void>();

function read(): string | null {
  if (!loaded) {
    cached = localStorage.getItem(STORAGE_KEY);
    loaded = true;
  }
  return cached;
}

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const authStore = {
  getToken(): string | null {
    return read();
  },
  setToken(token: string): void {
    cached = token;
    loaded = true;
    localStorage.setItem(STORAGE_KEY, token);
    notify();
  },
  clearToken(): void {
    cached = null;
    loaded = true;
    localStorage.removeItem(STORAGE_KEY);
    notify();
  },
};

/** The store as routes see it in the router context. */
export type AuthStore = typeof authStore;

/** Whether a session is open, as a subscription React can re-render on. */
export function useIsAuthenticated(): boolean {
  return useSyncExternalStore(subscribe, read) !== null;
}
