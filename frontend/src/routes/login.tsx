import { useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { login } from "@/lib/api/auth";
import { authStore } from "@/lib/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      authStore.setToken(data.access_token);
      void navigate({ to: "/" });
    },
  });

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    loginMutation.mutate({ email, password });
  }

  return (
    <Card className="mx-auto max-w-sm">
      <CardHeader>
        <CardTitle className="text-h2">{t("login.heading")}</CardTitle>
        <CardDescription>{t("login.subheading")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">{t("login.email")}</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">{t("login.password")}</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {loginMutation.isError ? (
            <p className="text-caption text-destructive">{t("login.error")}</p>
          ) : null}
          <Button type="submit" disabled={loginMutation.isPending}>
            {loginMutation.isPending
              ? t("login.submitting")
              : t("login.submit")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export const Route = createFileRoute("/login")({ component: LoginPage });
