import {
  Link,
  Outlet,
  createRootRouteWithContext,
  useNavigate,
} from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { type AuthStore, useIsAuthenticated } from "@/lib/auth-store";
import { endSession } from "@/lib/session";

/** What every route's `beforeLoad` receives: the auth state guards decide on. */
export interface RouterContext {
  auth: AuthStore;
}

function RootLayout() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isAuthenticated = useIsAuthenticated();

  function handleLogout(): void {
    endSession(queryClient);
    void navigate({ to: "/login" });
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <span className="text-h3">{t("app.title")}</span>
        <nav className="flex items-center gap-4 text-body">
          {isAuthenticated ? (
            <>
              <Link to="/" className="text-foreground hover:text-primary">
                {t("app.nav.items")}
              </Link>
              <Button variant="ghost" size="sm" onClick={handleLogout}>
                {t("app.nav.logout")}
              </Button>
            </>
          ) : (
            <Link to="/login" className="text-foreground hover:text-primary">
              {t("app.nav.login")}
            </Link>
          )}
        </nav>
      </header>
      <main className="px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
});
