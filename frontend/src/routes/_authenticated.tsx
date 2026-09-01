import { Outlet, createFileRoute, redirect } from "@tanstack/react-router";

/**
 * The gate in front of every page that needs a session.
 *
 * It is pathless, so the URLs underneath it are unchanged —
 * `routes/_authenticated/index.tsx` is still `/`. With no token we redirect
 * before the page renders, so a logged-out visit never fires a request that
 * comes back 401 and leaves an error state on screen.
 */
export const Route = createFileRoute("/_authenticated")({
  beforeLoad: ({ context }) => {
    if (!context.auth.getToken()) throw redirect({ to: "/login" });
  },
  component: Outlet,
});
