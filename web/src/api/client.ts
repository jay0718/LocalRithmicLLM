import createClient, { type Middleware } from "openapi-fetch";
import type { paths as ConsolePaths } from "./console";
import type { paths as GatewayPaths } from "./gateway";
import type { paths as GexPaths } from "./gex";
import { tokenStore } from "../auth/tokenStore";

const REQUEST_TIMEOUT_MS = 15_000;

/** One error shape for every failed request, whatever the backend or failure. */
export class ApiError extends Error {
  readonly status: number;
  readonly fieldErrors: Record<string, string>;

  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

/** Turn FastAPI and gateway error bodies into a message plus per-field messages. */
export function parseErrorBody(status: number, body: unknown): ApiError {
  const fallback = status === 0 ? "Could not reach the server" : `Request failed (${status})`;
  if (!body || typeof body !== "object") return new ApiError(status, fallback);
  const record = body as Record<string, unknown>;
  const gatewayError = record.error as { message?: string } | undefined;
  if (gatewayError?.message) return new ApiError(status, gatewayError.message);
  const detail = record.detail;
  if (typeof detail === "string") return new ApiError(status, detail);
  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const item of detail as ValidationItem[]) {
      const field = item.loc?.filter((part) => part !== "body").join(".") ?? "";
      if (field && item.msg && !fields[field]) fields[field] = item.msg;
    }
    return new ApiError(status, "Some fields need attention", fields);
  }
  return new ApiError(status, fallback);
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  async onResponse({ response }) {
    if (response.ok) return response;
    if (response.status === 401) tokenStore.expire();
    const body = await response
      .clone()
      .json()
      .catch(() => null);
    throw parseErrorBody(response.status, body);
  },
};

async function fetchWithTimeout(input: Request): Promise<Response> {
  try {
    return await fetch(input, {
      signal: AbortSignal.any([input.signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]),
    });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    throw new ApiError(0, timedOut ? "The server took too long to respond" : "Could not reach the server");
  }
}

function client<Paths extends object>(baseUrl: string) {
  const instance = createClient<Paths>({ baseUrl, fetch: fetchWithTimeout });
  instance.use(auth);
  return instance;
}

const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
export const consoleApi = client<ConsolePaths>(`${origin}/api/console`);
export const gexApi = client<GexPaths>(`${origin}/api/gex`);
export const gatewayApi = client<GatewayPaths>(`${origin}/api/gateway`);

/** Unwrap an openapi-fetch result, throwing ApiError on failure. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || !response.ok) throw parseErrorBody(response.status, error);
  return data as T;
}
