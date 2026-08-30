/**
 * Objectives, as the browser calls them.
 *
 * The save key is derived from the objective **and the version being saved**, which is what makes
 * autosave safe: a retry of "save version 7" is recognised as the same save, and the next edit is
 * version 8 and therefore a different operation. A fresh key per keystroke would make the header
 * decorative and a duplicate save indistinguishable from a real one.
 */

import { request } from "./client";
import { operationKey } from "./idempotency";
import type {
  CurrentStepRead,
  ObjectiveCreate,
  ObjectiveList,
  ObjectiveRead,
  ObjectiveUpdate,
  PersonRef,
  WorkbookLists,
} from "./contract";

/**
 * An objective with its lists filled in.
 *
 * Everything with a server-side default arrives optional in the generated contract, which is
 * correct — the server may add a field the client has not seen. Filling the defaults once, here,
 * beats `?? []` at a dozen call sites, where one of them would eventually be missed.
 */
export type Objective = Omit<ObjectiveRead, "current_steps"> & {
  current_steps: CurrentStepRead[];
};

/** Same, for the workbook's suggestion lists. */
export type Lists = { [K in keyof WorkbookLists]-?: string[] };

function fill(objective: ObjectiveRead): Objective {
  return { ...objective, current_steps: objective.current_steps ?? [] };
}

export function fetchObjectives(
  options: { status?: string; includeArchived?: boolean; signal?: AbortSignal } = {},
): Promise<ObjectiveList> {
  const search = new URLSearchParams();
  if (options.status) search.set("status", options.status);
  if (options.includeArchived) search.set("include_archived", "true");
  const query = search.toString();
  return request<ObjectiveList>(
    `/objectives${query ? `?${query}` : ""}`,
    options.signal ? { signal: options.signal } : {},
  );
}

export async function fetchObjective(
  id: string,
  signal?: AbortSignal,
): Promise<Objective> {
  return fill(
    await request<ObjectiveRead>(`/objectives/${id}`, signal ? { signal } : {}),
  );
}

/** The workbook's suggested values. Served, so the frontend keeps no second copy to drift. */
export async function fetchWorkbookLists(signal?: AbortSignal): Promise<Lists> {
  const lists = await request<WorkbookLists>(
    "/objectives/lists",
    signal ? { signal } : {},
  );
  return {
    departments: lists.departments ?? [],
    workload_units: lists.workload_units ?? [],
    triggers: lists.triggers ?? [],
    frequencies: lists.frequencies ?? [],
    work_places: lists.work_places ?? [],
    problems: lists.problems ?? [],
    approvals: lists.approvals ?? [],
  };
}

export function fetchPeople(signal?: AbortSignal): Promise<PersonRef[]> {
  return request<PersonRef[]>("/objectives/people", signal ? { signal } : {});
}

export function createObjective(
  body: ObjectiveCreate,
): Promise<{ id: string; version: string }> {
  return request<{ id: string; version: string }>("/objectives", {
    method: "POST",
    body,
    idempotencyKey: operationKey("objective-create", body.title),
  });
}

/**
 * Save the draft — the same call for autosave and for Save Draft.
 *
 * Returns the whole objective, so the client's copy and the server's cannot drift after a save
 * that changed something the client did not send.
 */
export async function saveObjective(
  id: string,
  body: ObjectiveUpdate,
): Promise<Objective> {
  return fill(
    await request<ObjectiveRead>(`/objectives/${id}`, {
      method: "PATCH",
      body,
      idempotencyKey: `objective-save:${id}:v${body.expected_version}`,
      expectedVersion: body.expected_version,
    }),
  );
}

export function archiveObjective(
  id: string,
  expectedVersion: number,
): Promise<{ id: string; version: string }> {
  return request<{ id: string; version: string }>(`/objectives/${id}/archive`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `objective-archive:${id}:v${expectedVersion}`,
    expectedVersion,
  });
}
