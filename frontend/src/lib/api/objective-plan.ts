/**
 * The analysis and the execution graph, as the browser calls them.
 *
 * One function per thing a person does, mirroring the routes — PLAN §7 lists them: add, edit,
 * delete, duplicate, merge, reorder, change dependencies. Each carries an idempotency key derived
 * from the operation and the version it acts on, so a retry after a dropped connection is
 * recognised as the same intent rather than applied twice.
 */

import { request } from "./client";
import type { PlanRead, StepKind, StepRead } from "./contract";

/** The plan with its optional fields filled in, so no call site has to write `?? []`. */
export type Plan = Omit<PlanRead, "steps"> & { steps: Step[] };
export type Step = Omit<StepRead, "depends_on"> & { depends_on: string[] };

function fill(plan: PlanRead): Plan {
  return {
    ...plan,
    steps: (plan.steps ?? []).map((step) => ({
      ...step,
      depends_on: step.depends_on ?? [],
    })),
  };
}

export async function fetchPlan(
  objectiveId: string,
  signal?: AbortSignal,
): Promise<Plan> {
  return fill(
    await request<PlanRead>(
      `/objectives/${objectiveId}/plan`,
      signal ? { signal } : {},
    ),
  );
}

/**
 * Run the analysis.
 *
 * Keyed on the objective and its version: analysing the same objective twice without changing
 * anything is the same request, and re-running after an edit is a different one. Which is the
 * behaviour somebody double-clicking the button wants.
 */
export async function analyse(
  objectiveId: string,
  objectiveVersion: number,
): Promise<Plan> {
  return fill(
    await request<PlanRead>(`/objectives/${objectiveId}/analyse`, {
      method: "POST",
      body: {},
      idempotencyKey: `analyse:${objectiveId}:v${objectiveVersion}`,
    }),
  );
}

export function addStep(
  objectiveId: string,
  body: {
    kind: StepKind;
    title: string;
    detail?: string | null;
    responsible_role?: string | null;
    after_step_id?: string | null;
  },
): Promise<{ id: string; version: string }> {
  return request(`/objectives/${objectiveId}/plan/steps`, {
    method: "POST",
    body,
    idempotencyKey: `step-add:${objectiveId}:${body.after_step_id ?? "end"}:${body.title}`,
  });
}

export function updateStep(
  objectiveId: string,
  stepId: string,
  body: Record<string, unknown> & { expected_version: number },
): Promise<{ id: string; version: string }> {
  return request(`/objectives/${objectiveId}/plan/steps/${stepId}`, {
    method: "PATCH",
    body,
    idempotencyKey: `step-update:${stepId}:v${body.expected_version}`,
    expectedVersion: body.expected_version,
  });
}

export function deleteStep(
  objectiveId: string,
  stepId: string,
  expectedVersion: number,
): Promise<{ status: string }> {
  return request(`/objectives/${objectiveId}/plan/steps/${stepId}/delete`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `step-delete:${stepId}:v${expectedVersion}`,
    expectedVersion,
  });
}

/**
 * Copy a step.
 *
 * `planSize` is in the key because the key alone was the step id, so a second duplicate of the
 * same step matched the first's stored response and returned the copy already made — the button
 * appeared to do nothing. The plan's size is what tells the two presses apart: duplicating this
 * step when there were four is a different operation from duplicating it when there were five,
 * and a retry of either still has the size it was sent with.
 */
export function duplicateStep(
  objectiveId: string,
  stepId: string,
  planSize: number,
): Promise<{ id: string }> {
  return request(`/objectives/${objectiveId}/plan/steps/${stepId}/duplicate`, {
    method: "POST",
    body: {},
    idempotencyKey: `step-duplicate:${stepId}:of${planSize}`,
  });
}

/**
 * Fold one step into another, deleting the one absorbed.
 *
 * The version is the version of the step that disappears. Every other mutation on a step carried
 * one and this — the only one that deletes — did not, so a merge could absorb a step somebody had
 * rewritten a moment earlier and take the rewrite with it.
 */
export function mergeStep(
  objectiveId: string,
  stepId: string,
  intoStepId: string,
  expectedVersion: number,
): Promise<{ id: string }> {
  return request(`/objectives/${objectiveId}/plan/steps/${stepId}/merge`, {
    method: "POST",
    body: { into_step_id: intoStepId, expected_version: expectedVersion },
    idempotencyKey: `step-merge:${stepId}:${intoStepId}:v${expectedVersion}`,
    expectedVersion,
  });
}

/** The whole order. A partial move needs both sides to agree on the other positions. */
export function reorderPlan(
  objectiveId: string,
  order: string[],
): Promise<{ status: string }> {
  return request(`/objectives/${objectiveId}/plan/order`, {
    method: "PUT",
    body: { order },
    //  The order itself is the operation: the same arrangement sent twice is one change.
    idempotencyKey: `plan-order:${objectiveId}:${order.join(",").slice(0, 150)}`,
  });
}

/**
 * Replace what this step waits for.
 *
 * The version is in the body because the server checks it — the set is replaced, not added to, so
 * an edit made against an older view of it silently drops whatever appeared in between. And in the
 * key, which is what fixes un-ticking a box and ticking it again: that re-sent a key *and* a body
 * the server had already answered, so the tick did not come back. The step's version moves with
 * each set, so the second attempt is a different operation.
 */
export function setDependencies(
  objectiveId: string,
  stepId: string,
  dependsOn: string[],
  expectedVersion: number,
): Promise<{ status: string }> {
  return request(`/objectives/${objectiveId}/plan/steps/${stepId}/dependencies`, {
    method: "PUT",
    body: { depends_on: dependsOn, expected_version: expectedVersion },
    idempotencyKey: `step-deps:${stepId}:v${expectedVersion}`,
    expectedVersion,
  });
}
