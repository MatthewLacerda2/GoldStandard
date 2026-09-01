import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import "@/i18n";
import "@/styles.css";
import { routeTree } from "@/routeTree.gen";
import { authStore } from "@/lib/auth-store";
import { createQueryClient } from "@/lib/query-client";
import { endSession } from "@/lib/session";

// Auth lives in the router context, so a guard can decide in `beforeLoad` —
// before a protected page renders or fetches anything.
const router = createRouter({ routeTree, context: { auth: authStore } });

// A 401 means the token is gone or expired: end the session and go sign in
// again, so a stale token heals itself instead of dead-ending on an error.
const queryClient = createQueryClient((client) => {
  endSession(client);
  void router.navigate({ to: "/login" });
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Root element not found");

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
