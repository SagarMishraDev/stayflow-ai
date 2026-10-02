import axios, { AxiosError } from "axios";

/** Base URL of the staff API. Relative by default (same-origin deploy). */
export const API_BASE =
  import.meta.env.VITE_API_URL ?? "/api/v1";

const TOKEN_KEY = "stayflow_token";

/**
 * NOTE: the JWT lives in localStorage here for simplicity. The
 * production-grade choice is an httpOnly, Secure, SameSite cookie set by
 * the backend so JS can never read the token; that requires a backend
 * change, so it is out of scope for this frontend pass.
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // Session is dead (expired/invalid/revoked token): drop it and send the
    // user back to login instead of leaving every query failing.
    if (error.response?.status === 401 && getToken()) {
      clearToken();
      if (!window.location.pathname.endsWith("/login")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);

/** Human-readable message from a FastAPI error response. */
export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: unknown } | undefined;
    if (data && typeof data.detail === "string" && data.detail) return data.detail;
    if (error.response) return `Request failed (${error.response.status})`;
    return "Could not reach the server. Check your connection and try again.";
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

/** Exact 401 messages the backend returns (app/core/security.py). */
export const AUTH_401_MESSAGES: Record<string, string> = {
  "Invalid email or password":
    "That email and password combination was not recognised. Try again.",
  "Not authenticated": "Your session is missing. Please sign in again.",
  "Token has expired": "Your session has expired. Please sign in again.",
  "Invalid token": "Your session is invalid. Please sign in again.",
  "User is inactive or no longer exists":
    "This staff account is no longer active. Contact your hotel admin.",
  "Token role does not match user account":
    "Your account changed since you signed in. Please sign in again.",
};
