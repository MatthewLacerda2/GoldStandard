import type { QueryClient } from "@tanstack/react-query";
import { authStore } from "@/lib/auth-store";

/**
 * End the session: drop the token and everything it fetched, so the next user
 * never sees the previous one's data. Both endings come through here — the user
 * logging out, and the API rejecting the token with a 401. Where to go next is
 * left to the caller, which knows where it is.
 */
export function endSession(queryClient: QueryClient): void {
  authStore.clearToken();
  queryClient.clear();
}
