import { createRootRoute, Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

function RootLayout() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <span className="text-h3">{t("app.title")}</span>
        <nav className="flex gap-4 text-body">
          <Link to="/" className="text-foreground hover:text-primary">
            {t("app.nav.items")}
          </Link>
          <Link to="/login" className="text-foreground hover:text-primary">
            {t("app.nav.login")}
          </Link>
        </nav>
      </header>
      <main className="px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

export const Route = createRootRoute({ component: RootLayout });
