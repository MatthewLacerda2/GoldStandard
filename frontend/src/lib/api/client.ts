import { authStore } from "@/lib/auth-store";

/**
 * The one place HTTP and auth live. Pages never call `fetch`; they go through
 * the typed `lib/api/<domain>.ts` wrappers, which call `request()` here. This
 * keeps the bearer token, base URL, and error shape in a single module.
 *
 * In production the app is served behind a reverse proxy, so the relative
 * `/api/v1` default just works. Point `VITE_API_URL` at the backend origin
 * (e.g. http://localhost:8000/api/v1) when running the dev server standalone.
 */
const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1";

/** A non-2xx response, carrying the HTTP status and the backend's detail. */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body } = options;
  const headers: Record<string, string> = {};
  const token = authStore.getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await detail(response));
  }
  // 204 No Content (e.g. DELETE) has no body to parse.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Pull FastAPI's `{ detail }` off an error response, falling back to status. */
async function detail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string };
    return data.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}
