import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${status}`;
    super(`ApiError ${status}: ${detail}`);
    this.status = status;
    this.body = body;
  }
}

function apiBase(): string {
  const raw = import.meta.env.VITE_API_BASE;
  return typeof raw === "string" && raw.length > 0 ? raw : "/api";
}

function apiKey(): string {
  const raw = import.meta.env.VITE_API_KEY;
  return typeof raw === "string" ? raw : "";
}

function buildHeaders(hasJsonBody: boolean): Record<string, string> {
  const headers: Record<string, string> = {};
  if (hasJsonBody) headers["Content-Type"] = "application/json";
  const key = apiKey();
  if (key.length > 0) headers["X-API-Key"] = key;
  return headers;
}

async function parseBody(resp: Response): Promise<unknown> {
  if (resp.status === 204) return undefined;
  const ct = resp.headers.get("content-type") ?? "";
  const text = await resp.text();
  if (text.length === 0) return undefined;
  if (ct.includes("application/json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const url = apiBase().replace(/\/$/, "") + path;
  const hasJson = body !== undefined && body !== null;
  const init: RequestInit = {
    method,
    headers: buildHeaders(hasJson),
  };
  if (hasJson) init.body = JSON.stringify(body);

  const resp = await fetch(url, init);
  const parsed = await parseBody(resp);

  if (!resp.ok) {
    throw new ApiError(resp.status, parsed as ApiErrorBody);
  }
  return parsed as T;
}

export const client = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

// Exposed for tests that want to reach the raw helpers without hitting network.
export const __internal = { apiBase, apiKey, buildHeaders, parseBody };
