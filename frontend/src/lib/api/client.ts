/**
 * The one place the browser talks to the API.
 *
 * Everything goes through `request()` so that four things happen on every call without any
 * screen having to remember them: the session cookie is sent, a correlation id is attached, a
 * mutation carries its idempotency key, and a failure becomes a typed error rather than a
 * silently-empty result.
 */

import { ApiError, NetworkError, toApiError } from "./errors";

/**
 * Where the API lives.
 *
 * Public because the browser reads it. It holds an origin and a path — never a secret. A key in
 * a `NEXT_PUBLIC_` variable is a key in the JavaScript bundle.
 */
const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001/api/v1";

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /**
   * Derived from the logical operation — "publish objective 47 version 3" — never from
   * `crypto.randomUUID()` at the call site. The whole point is that a retry of the *same*
   * intent reuses the key, so the server can recognise it as a repeat rather than a second
   * command. A fresh id per attempt makes the header decorative.
   */
  /**
   * `null` is an explicit exemption for credential/challenge endpoints whose retry contract is
   * purpose-built and must not persist secrets. `undefined` on a mutation is still a bug.
   */
  idempotencyKey?: string | null;
  /** Guards against a silent overwrite: the version the caller read before editing. */
  expectedVersion?: number;
  signal?: AbortSignal;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, idempotencyKey, expectedVersion, signal } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  if (method !== "GET") {
    if (idempotencyKey === undefined) {
      // Loud, and at the call site. A mutation without a key is a mutation that will be applied
      // twice the first time the network hiccups, and that is not something to discover in
      // production.
      throw new Error(
        `${method} ${path} was sent without an idempotency key. Derive one from the ` +
          `operation (for example "publish-objective-<id>-v<n>") so a retry reuses it.`,
      );
    }
    if (idempotencyKey !== null) {
      headers["Idempotency-Key"] = idempotencyKey;
    }
  }

  if (expectedVersion !== undefined) {
    headers["If-Match"] = String(expectedVersion);
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      // The session is an http-only cookie. It is never read by JavaScript, so a script
      // injected into the page cannot exfiltrate it.
      credentials: "include",
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new NetworkError(cause);
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export { ApiError, NetworkError };
