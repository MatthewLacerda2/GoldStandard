import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/client";

/**
 * The query client, and with it the one place an expired session is noticed.
 *
 * `client.ts` stays a pure fetch layer: it throws a typed `ApiError` and knows
 * nothing about routing. Every query and mutation failure passes through here
 * instead, so a 401 is handled once no matter which call produced it.
 */
export function createQueryClient(
  onUnauthorized: (queryClient: QueryClient) => void,
): QueryClient {
  function handleError(error: unknown): void {
    if (error instanceof ApiError && error.status === 401) {
      onUnauthorized(queryClient);
    }
  }

  const queryClient = new QueryClient({
    queryCache: new QueryCache({ onError: handleError }),
    mutationCache: new MutationCache({ onError: handleError }),
  });

  return queryClient;
}
