/**
 * Supervisors, as the browser calls them.
 *
 * The same shape as `agents.ts`, with one difference that is `PLAN.md` §10's rather than a
 * stylistic one: **the two scopes are two calls**. `saveSupervisor` carries the design and the
 * supervised set; `setHandler` and `removeHandler` carry who may control it. They are separate
 * because one is `edit_draft` and the other is `manage_access`, and a single call carrying both
 * would let the looser permission decide the stricter one.
 */

import { request } from "./client";
import type {
  HandlerRead,
  SimulationInput,
  SimulationList,
  SupervisorCreate,
  SupervisorList,
  SupervisorLists,
  SupervisorPublishSummary,
  SupervisorRead,
  SupervisorScheduleRead,
  SupervisorScheduleWrite,
  SupervisorUpdate,
  SupervisorVersionList,
} from "./contract";

/** The supervisor with its collections filled in, so no call site writes `?? []`. */
export type Supervisor = Omit<
  SupervisorRead,
  | "supervised"
  | "handlers"
  | "dependencies"
  | "quality_gates"
  | "escalations"
  | "notifications"
  | "my_actions"
> & {
  supervised: NonNullable<SupervisorRead["supervised"]>;
  handlers: NonNullable<SupervisorRead["handlers"]>;
  dependencies: NonNullable<SupervisorRead["dependencies"]>;
  quality_gates: NonNullable<SupervisorRead["quality_gates"]>;
  escalations: NonNullable<SupervisorRead["escalations"]>;
  notifications: NonNullable<SupervisorRead["notifications"]>;
  my_actions: NonNullable<SupervisorRead["my_actions"]>;
};

function fill(supervisor: SupervisorRead): Supervisor {
  return {
    ...supervisor,
    supervised: supervisor.supervised ?? [],
    handlers: supervisor.handlers ?? [],
    dependencies: supervisor.dependencies ?? [],
    quality_gates: supervisor.quality_gates ?? [],
    escalations: supervisor.escalations ?? [],
    notifications: supervisor.notifications ?? [],
    my_actions: supervisor.my_actions ?? [],
  };
}

export function fetchSupervisors(
  options: { status?: string; signal?: AbortSignal } = {},
): Promise<SupervisorList> {
  const search = new URLSearchParams();
  if (options.status) search.set("status", options.status);
  const query = search.toString();
  return request<SupervisorList>(
    `/supervisors${query ? `?${query}` : ""}`,
    options.signal ? { signal: options.signal } : {},
  );
}

export async function fetchSupervisor(
  id: string,
  signal?: AbortSignal,
): Promise<Supervisor> {
  return fill(
    await request<SupervisorRead>(`/supervisors/${id}`, signal ? { signal } : {}),
  );
}

export type SupervisorVocabulary = {
  [K in keyof SupervisorLists]-?: NonNullable<SupervisorLists[K]>;
};

export async function fetchSupervisorLists(
  signal?: AbortSignal,
): Promise<SupervisorVocabulary> {
  const lists = await request<SupervisorLists>(
    "/supervisors/lists",
    signal ? { signal } : {},
  );
  return {
    kinds: lists.kinds ?? [],
    handler_roles: lists.handler_roles ?? [],
    on_failure: lists.on_failure ?? [],
    simulation_statuses: lists.simulation_statuses ?? [],
  };
}

export function createSupervisor(
  body: SupervisorCreate,
): Promise<{ id: string; version: string }> {
  return request("/supervisors", {
    method: "POST",
    body,
    idempotencyKey: `supervisor-create:${body.name}`,
  });
}

export async function saveSupervisor(
  id: string,
  body: SupervisorUpdate,
): Promise<Supervisor> {
  return fill(
    await request<SupervisorRead>(`/supervisors/${id}`, {
      method: "PUT",
      body,
      idempotencyKey: `supervisor-save:${id}:v${body.expected_version}`,
      expectedVersion: body.expected_version,
    }),
  );
}

// ------------------------------------------------------------------------ scope 2

/**
 * Add or change a handler.
 *
 * Its own call and its own permission. §10's two scopes are independent, and this is where that
 * shows up in the client: nothing about a handler travels in the design payload.
 */
export function setHandler(
  supervisorId: string,
  membershipId: string,
  role: string,
  expectedVersion: number,
): Promise<HandlerRead> {
  return request<HandlerRead>(
    `/supervisors/${supervisorId}/handlers/${membershipId}`,
    {
      method: "PUT",
      body: { membership_id: membershipId, role, expected_version: expectedVersion },
      idempotencyKey: `supervisor-handler:${supervisorId}:${membershipId}:${role}:v${expectedVersion}`,
      expectedVersion,
    },
  );
}

export function removeHandler(
  supervisorId: string,
  membershipId: string,
  expectedVersion: number,
): Promise<{ removed: string }> {
  return request(`/supervisors/${supervisorId}/handlers/${membershipId}`, {
    method: "DELETE",
    body: { expected_version: expectedVersion },
    idempotencyKey: `supervisor-handler-remove:${supervisorId}:${membershipId}:v${expectedVersion}`,
    expectedVersion,
  });
}

// ------------------------------------------------------------------------ schedule

export function setSupervisorSchedule(
  supervisorId: string,
  body: SupervisorScheduleWrite,
): Promise<SupervisorScheduleRead> {
  return request<SupervisorScheduleRead>(`/supervisors/${supervisorId}/schedule`, {
    method: "PUT",
    body,
    idempotencyKey: `supervisor-schedule:${supervisorId}:v${body.expected_version}`,
    expectedVersion: body.expected_version,
  });
}

// ------------------------------------------------------------------------ simulation and publish

export function fetchSimulations(
  supervisorId: string,
  signal?: AbortSignal,
): Promise<SimulationList> {
  return request<SimulationList>(
    `/supervisors/${supervisorId}/simulations`,
    signal ? { signal } : {},
  );
}

export function saveSimulations(
  supervisorId: string,
  simulations: SimulationInput[],
  expectedVersion: number,
): Promise<SimulationList> {
  return request<SimulationList>(`/supervisors/${supervisorId}/simulations`, {
    method: "PUT",
    body: { simulations, expected_version: expectedVersion },
    idempotencyKey: `supervisor-simulations:${supervisorId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export type SupervisorSummary = Omit<
  SupervisorPublishSummary,
  "warnings" | "gates"
> & {
  warnings: { code: string; message: string }[];
  gates: { gate: string; name: string; passed: boolean; reason: string }[];
};

export async function fetchSupervisorPublishSummary(
  supervisorId: string,
  signal?: AbortSignal,
): Promise<SupervisorSummary> {
  const summary = await request<SupervisorPublishSummary>(
    `/supervisors/${supervisorId}/publish`,
    signal ? { signal } : {},
  );
  return { ...summary, warnings: summary.warnings ?? [], gates: summary.gates ?? [] };
}

function transition(
  supervisorId: string,
  action: "submit" | "withdraw" | "publish",
  expectedVersion: number,
): Promise<Record<string, string>> {
  return request(`/supervisors/${supervisorId}/${action}`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `supervisor-${action}:${supervisorId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export const submitSupervisor = (id: string, version: number) =>
  transition(id, "submit", version);
export const withdrawSupervisor = (id: string, version: number) =>
  transition(id, "withdraw", version);
export const publishSupervisor = (id: string, version: number) =>
  transition(id, "publish", version);

export function fetchSupervisorVersions(
  supervisorId: string,
  signal?: AbortSignal,
): Promise<SupervisorVersionList> {
  return request<SupervisorVersionList>(
    `/supervisors/${supervisorId}/versions`,
    signal ? { signal } : {},
  );
}
