import createClient from "openapi-fetch";

import type { paths } from "./schema";
import { clearAccessToken, getAccessToken, setAccessToken } from "./tokenStore";

export interface ApiErrorPayload {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, payload: Partial<ApiErrorPayload>) {
    super(payload.message || "Une erreur réseau ou serveur est survenue.");
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code || "API_ERROR";
    this.details = payload.details || {};
  }
}

let refreshPromise: Promise<string | null> | null = null;
let onSessionExpiredCallback: (() => void) | null = null;

export function registerSessionExpiredHandler(handler: () => void): void {
  onSessionExpiredCallback = handler;
}

/**
 * Mutualise les appels concurrents à /api/v1/auth/refresh/ afin d'éviter
 * plusieurs rotations simultanées du cookie HttpOnly.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch("/api/v1/auth/refresh/", {
          method: "POST",
          credentials: "include",
          headers: { Accept: "application/json" },
        });
        if (!res.ok) {
          clearAccessToken();
          return null;
        }
        const data = (await res.json()) as { access_token?: string };
        if (data.access_token) {
          setAccessToken(data.access_token);
          return data.access_token;
        }
        clearAccessToken();
        return null;
      } catch {
        clearAccessToken();
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

const AUTH_SKIP_RETRY_PATHS = [
  "/api/v1/auth/login/",
  "/api/v1/auth/register/",
  "/api/v1/auth/refresh/",
  "/api/v1/auth/logout/",
];

const authFetch: typeof fetch = async (input, init) => {
  const originalRequest = input instanceof Request ? input : new Request(input, init);
  const url = new URL(originalRequest.url, window.location.origin);
  const skipRetry = AUTH_SKIP_RETRY_PATHS.some((path) => url.pathname.endsWith(path));

  const buildRequest = (token: string | null): Request => {
    const req = originalRequest.clone();
    const headers = new Headers(req.headers);
    if (token && !skipRetry) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return new Request(req, { headers, credentials: "include" });
  };

  let response = await fetch(buildRequest(getAccessToken()));

  if (response.status === 401 && !skipRetry) {
    const nextToken = await refreshAccessToken();
    if (nextToken) {
      response = await fetch(buildRequest(nextToken));
    } else {
      onSessionExpiredCallback?.();
    }
  }

  return response;
};

export const apiClient = createClient<paths>({
  baseUrl: "",
  fetch: authFetch,
});

export function extractApiError(error: unknown, fallbackStatus = 500): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error && typeof error === "object") {
    const payload = error as Partial<ApiErrorPayload>;
    if (typeof payload.message === "string" || typeof payload.code === "string") {
      return new ApiError(fallbackStatus, payload);
    }
  }
  return new ApiError(fallbackStatus, {
    code: "NETWORK_ERROR",
    message: "Impossible de joindre le serveur. Vérifiez votre connexion.",
  });
}
