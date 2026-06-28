/** Mirrors backend `schemas/auth.py`. Keep in sync with the Pydantic models. */

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}
