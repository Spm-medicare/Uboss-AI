/**
 * The publish summary, the submission and the approval.
 *
 * Three calls because they are three decisions by up to two people. Each key is derived from the
 * objective and the version being acted on — so a retry is the same decision, and a decision made
 * on a newer version is a different one.
 */

import { request } from "./client";
import type { PublishSummary, VersionRead } from "./contract";

/** With the optional fields filled in, so no call site writes `?? []`. */
export type Summary = Omit<PublishSummary, "warnings"> & {
  warnings: { code: string; message: string }[];
};

export async function fetchPublishSummary(
  objectiveId: string,
  signal?: AbortSignal,
): Promise<Summary> {
  const summary = await request<PublishSummary>(
    `/objectives/${objectiveId}/publish`,
    signal ? { signal } : {},
  );
  return { ...summary, warnings: summary.warnings ?? [] };
}

export function submitObjective(
  objectiveId: string,
  expectedVersion: number,
): Promise<{ status: string; version: string }> {
  return request(`/objectives/${objectiveId}/submit`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `objective-submit:${objectiveId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function withdrawObjective(
  objectiveId: string,
  expectedVersion: number,
): Promise<{ status: string; version: string }> {
  return request(`/objectives/${objectiveId}/withdraw`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `objective-withdraw:${objectiveId}:v${expectedVersion}`,
    expectedVersion,
  });
}

/**
 * Approve and publish.
 *
 * The version is the point: it is the difference between approving what you read and approving
 * whatever it has become since. The server refuses a mismatch rather than resolving it.
 */
export function publishObjective(
  objectiveId: string,
  expectedVersion: number,
): Promise<{ version_id: string; version_no: string }> {
  return request(`/objectives/${objectiveId}/publish`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `objective-publish:${objectiveId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function fetchVersions(
  objectiveId: string,
  signal?: AbortSignal,
): Promise<VersionRead[]> {
  return request<VersionRead[]>(
    `/objectives/${objectiveId}/versions`,
    signal ? { signal } : {},
  );
}
