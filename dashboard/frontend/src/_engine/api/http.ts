/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
/**
 * Shared HTTP transport for every bot dashboard.
 *
 * One hardened fetch wrapper plus typed errors, so every dashboard talks to its API
 * and handles failures identically. Each bot builds its own `api` object of endpoint
 * methods on top of `apiFetch` in its own `api/client.ts` seam (endpoints are
 * bot-specific; the transport is not).
 *
 * Error model: `apiFetch` THROWS typed errors (UnauthorizedError, TimeoutError,
 * ApiError) - it never renders. The one auth exception: on a 401 it calls the
 * configured `onUnauthorized` handler (default: redirect to /login, preserving
 * `?next`, and a no-op when already on /login) AND throws UnauthorizedError. So every
 * app lands on /login the same way, while callers can still react to the throw (e.g.
 * formatError -> "session expired"). Override via `configureApi` if a bot needs to.
 */

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const DEFAULT_TIMEOUT_MS = 15000;

export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

export class TimeoutError extends Error {
  constructor() {
    super("Request timed out");
    this.name = "TimeoutError";
  }
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function defaultRedirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return; // already there - avoid a loop
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/login?next=${next}`;
}

let _baseUrl = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
let _onUnauthorized: (() => void) | null = defaultRedirectToLogin;

/** Override transport config at startup (base URL, or the 401 handler; pass
 *  `onUnauthorized: null` to disable the auto-redirect). */
export function configureApi(opts: { baseUrl?: string; onUnauthorized?: (() => void) | null }): void {
  if (opts.baseUrl !== undefined) _baseUrl = opts.baseUrl.replace(/\/$/, "");
  if ("onUnauthorized" in opts) _onUnauthorized = opts.onUnauthorized ?? null;
}

/** Resolve a path against the configured base URL (absolute URLs pass through). */
export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${_baseUrl}${path}`;
}

let _csrfToken: string | null = null;
let _csrfInFlight: Promise<string | null> | null = null;

async function fetchCsrfToken(): Promise<string | null> {
  const res = await fetch(`${_baseUrl}/auth/csrf`, { credentials: "include" });
  if (!res.ok) return null;
  const body = (await res.json().catch(() => ({}))) as { csrf_token?: string };
  return body.csrf_token ?? null;
}

async function ensureCsrf(force = false): Promise<string | null> {
  if (force) _csrfToken = null;
  if (_csrfToken) return _csrfToken;
  if (!_csrfInFlight) {
    _csrfInFlight = fetchCsrfToken().finally(() => {
      _csrfInFlight = null;
    });
  }
  const token = await _csrfInFlight;
  if (token) _csrfToken = token;
  return token;
}

async function rawFetch(url: string, init: RequestInit): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), DEFAULT_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

export interface ApiOptions extends RequestInit {
  /** When true, a 401 still throws UnauthorizedError but does NOT trigger the
   *  onUnauthorized redirect. Use for the "am I logged in?" probe (api.me) and on
   *  public pages, where a 401 is a valid answer, not a session that just expired. */
  suppressAuthHandler?: boolean;
}

export async function apiFetch<T>(path: string, init?: ApiOptions): Promise<T> {
  const { suppressAuthHandler, ...requestInit } = init ?? {};
  const method = (requestInit.method ?? "GET").toUpperCase();
  const isUnsafe = UNSAFE_METHODS.has(method);
  const url = apiUrl(path);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(requestInit.headers as Record<string, string> | undefined),
  };
  if (isUnsafe) {
    const token = await ensureCsrf();
    if (token) headers["X-CSRF-Token"] = token;
  }

  const send = () => rawFetch(url, { credentials: "include", ...requestInit, method, headers });

  let res: Response;
  try {
    res = await send();
  } catch (e) {
    if ((e as Error).name === "AbortError") throw new TimeoutError();
    throw e;
  }

  // The CSRF token can rotate; on a CSRF-specific 403 refresh it once and retry.
  if (isUnsafe && res.status === 403) {
    const body = await res.clone().json().catch(() => ({}));
    if (/csrf/i.test(String(body?.detail ?? ""))) {
      const token = await ensureCsrf(true);
      if (token) {
        headers["X-CSRF-Token"] = token;
        res = await send();
      }
    }
  }

  if (res.status === 401) {
    _csrfToken = null;
    if (!suppressAuthHandler) _onUnauthorized?.();
    throw new UnauthorizedError();
  }
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    throw new ApiError(res.status, formatDetail(body.detail));
  }
  return (await res.json()) as T;
}

/** Flatten an error `detail` to something a human can read.
 *
 * Hand-written raises carry a string, but FastAPI's own 422 validation errors
 * carry a LIST of error objects - and stringifying that array produced
 * unreadable text in every error banner (found 2026-08-24). Each entry becomes
 * "field: message", joined with "; ". */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const err = d as { loc?: unknown; msg?: unknown };
        const loc = Array.isArray(err?.loc)
          ? err.loc.filter((part) => part !== "body").join(".")
          : "";
        const msg = typeof err?.msg === "string" ? err.msg : JSON.stringify(d);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("; ");
  }
  return detail == null ? "" : String(detail);
}

export function discordLoginUrl(redirectTo?: string): string {
  const qs = redirectTo ? `?redirect_to=${encodeURIComponent(redirectTo)}` : "";
  return `/auth/discord${qs}`;
}

export function logoutUrl(): string {
  return "/auth/logout";
}
