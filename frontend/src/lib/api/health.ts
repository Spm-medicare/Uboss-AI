/**
 * The API's readiness probe, as read by the browser.
 *
 * Sits outside the versioned surface on purpose: `/health/ready` is an operational endpoint, not
 * a product route, and it must keep answering while the versioned API is being replaced.
 */

import { NetworkError } from "./errors";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001/api/v1";

/** The API origin, with the versioned path removed. */
const ORIGIN = BASE_URL.replace(/\/api\/v\d+\/?$/, "");

export interface DependencyStatus {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Readiness {
  status: "ready" | "degraded";
  dependencies: DependencyStatus[];
}

/**
 * Ask the API whether it can serve traffic.
 *
 * A degraded answer arrives with HTTP 503 and a body describing what is down, so the 503 is
 * read rather than thrown — the body is the useful part. Anything else that goes wrong becomes
 * an error the caller must render; it never resolves to a fake "ready".
 */
export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  let response: Response;
  try {
    response = await fetch(`${ORIGIN}/health/ready`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new NetworkError(cause);
  }

  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`The API answered ${response.status} on its readiness probe.`);
  }

  return (await response.json()) as Readiness;
}
