/**
 * What a schedule actually did — §8's history, as the browser reads it.
 *
 * The preview beside it answers *"when will this run"*. This answers *"when did it, and when did
 * it not"*, and the second question is the one people ask. A schedule that skipped every bank
 * holiday is behaving correctly, and a history that hid its skips would make it look broken twice
 * a year.
 *
 * **There is no `createFiring`.** A firing exists because the scheduler recorded an occurrence.
 */

import { request } from "./client";
import type { FiringRead } from "./contract";
import { operationKey } from "./idempotency";

export async function fetchFirings(
  jobId: string,
  signal?: AbortSignal,
): Promise<FiringRead[]> {
  return request<FiringRead[]>(`/jobs/${jobId}/schedule/firings?limit=20`, {
    ...(signal ? { signal } : {}),
  });
}

/** Let a held occurrence run — §8's `requires_approval_per_run`, decided by a person. */
export async function releaseFiring(firingId: string): Promise<FiringRead> {
  return request<FiringRead>(`/schedule-firings/${firingId}/release`, {
    method: "POST",
    idempotencyKey: operationKey("firing-release", firingId),
  });
}
