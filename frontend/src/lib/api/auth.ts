import { request } from "@/lib/api/client";
import type { LoginRequest, TokenResponse } from "@/lib/schemas/auth";

/** Exchange credentials for an access token (`POST /auth/login`). */
export function login(credentials: LoginRequest): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: credentials,
  });
}
