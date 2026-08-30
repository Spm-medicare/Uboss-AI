/**
 * Jobs, as the browser calls them.
 *
 * The same shape as `objectives.ts` on purpose: one save call for autosave and Save Draft, keys
 * derived from the version being written, and the whole record returned so the client's copy and
 * the server's cannot drift.
 */

import { request } from "./client";
import { operationKey } from "./idempotency";
import type {
  JobCreate,
  JobList,
  JobPublishSummary,
  JobRead,
  JobUpdate,
  JobVersionRead,
  JobWorkbookLists,
  SchedulePreview,
  ScheduleRead,
  ScheduleWrite,
} from "./contract";

/** The job with its collections filled in, so no call site has to write `?? []`. */
export type Job = Omit<
  JobRead,
  "steps" | "assignment_rules" | "inputs" | "tools"
> & {
  steps: NonNullable<JobRead["steps"]>;
  assignment_rules: NonNullable<JobRead["assignment_rules"]>;
  inputs: NonNullable<JobRead["inputs"]>;
  tools: NonNullable<JobRead["tools"]>;
};

export type Lists = { [K in keyof JobWorkbookLists]-?: string[] };

function fill(job: JobRead): Job {
  return {
    ...job,
    steps: job.steps ?? [],
    assignment_rules: job.assignment_rules ?? [],
    inputs: job.inputs ?? [],
    tools: job.tools ?? [],
  };
}

export function fetchJobs(
  options: { status?: string; objectiveId?: string; signal?: AbortSignal } = {},
): Promise<JobList> {
  const search = new URLSearchParams();
  if (options.status) search.set("status", options.status);
  if (options.objectiveId) search.set("objective_id", options.objectiveId);
  const query = search.toString();
  return request<JobList>(
    `/jobs${query ? `?${query}` : ""}`,
    options.signal ? { signal: options.signal } : {},
  );
}

export async function fetchJob(id: string, signal?: AbortSignal): Promise<Job> {
  return fill(await request<JobRead>(`/jobs/${id}`, signal ? { signal } : {}));
}

export async function fetchJobLists(signal?: AbortSignal): Promise<Lists> {
  const lists = await request<JobWorkbookLists>(
    "/jobs/lists",
    signal ? { signal } : {},
  );
  return {
    departments: lists.departments ?? [],
    triggers: lists.triggers ?? [],
    frequencies: lists.frequencies ?? [],
    work_places: lists.work_places ?? [],
    approvals: lists.approvals ?? [],
    time_units: lists.time_units ?? [],
    input_types: lists.input_types ?? [],
    methods: lists.methods ?? [],
    approval_timings: lists.approval_timings ?? [],
    missing_actions: lists.missing_actions ?? [],
    failure_actions: lists.failure_actions ?? [],
    output_formats: lists.output_formats ?? [],
    permissions: lists.permissions ?? [],
  };
}

export function createJob(body: JobCreate): Promise<{ id: string; version: string }> {
  return request("/jobs", {
    method: "POST",
    body,
    idempotencyKey: operationKey("job-create", body.name),
  });
}

export async function saveJob(id: string, body: JobUpdate): Promise<Job> {
  return fill(
    await request<JobRead>(`/jobs/${id}`, {
      method: "PATCH",
      body,
      idempotencyKey: `job-save:${id}:v${body.expected_version}`,
      expectedVersion: body.expected_version,
    }),
  );
}

// ------------------------------------------------------------------------- schedule

export function fetchSchedule(
  jobId: string,
  signal?: AbortSignal,
): Promise<ScheduleRead | null> {
  return request<ScheduleRead | null>(
    `/jobs/${jobId}/schedule`,
    signal ? { signal } : {},
  );
}

/**
 * When this would actually run.
 *
 * `from` exists so somebody configuring in July can look at October — which is when the clocks
 * change, and the one thing about a schedule that cannot be reasoned about from its settings.
 */
export function previewSchedule(
  jobId: string,
  options: { count?: number; from?: string; signal?: AbortSignal } = {},
): Promise<SchedulePreview> {
  const search = new URLSearchParams();
  if (options.count) search.set("count", String(options.count));
  if (options.from) search.set("from_time", options.from);
  const query = search.toString();
  return request<SchedulePreview>(
    `/jobs/${jobId}/schedule/preview${query ? `?${query}` : ""}`,
    options.signal ? { signal: options.signal } : {},
  );
}

export function saveSchedule(
  jobId: string,
  body: ScheduleWrite,
): Promise<ScheduleRead> {
  return request<ScheduleRead>(`/jobs/${jobId}/schedule`, {
    method: "PUT",
    body,
    idempotencyKey: `job-schedule:${jobId}:v${body.expected_version ?? "new"}`,
  });
}

export function removeSchedule(jobId: string): Promise<void> {
  return request<void>(`/jobs/${jobId}/schedule`, {
    method: "DELETE",
    idempotencyKey: `job-schedule-remove:${jobId}`,
  });
}

// -------------------------------------------------------------------------- publish

export type JobSummary = Omit<JobPublishSummary, "warnings"> & {
  warnings: { code: string; message: string }[];
};

export async function fetchJobPublishSummary(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobSummary> {
  const summary = await request<JobPublishSummary>(
    `/jobs/${jobId}/publish`,
    signal ? { signal } : {},
  );
  return { ...summary, warnings: summary.warnings ?? [] };
}

export function submitJob(
  jobId: string,
  expectedVersion: number,
): Promise<{ status: string; version: string }> {
  return request(`/jobs/${jobId}/submit`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `job-submit:${jobId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function withdrawJob(
  jobId: string,
  expectedVersion: number,
): Promise<{ status: string; version: string }> {
  return request(`/jobs/${jobId}/withdraw`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `job-withdraw:${jobId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function publishJob(
  jobId: string,
  expectedVersion: number,
): Promise<{ version_id: string; version_no: string }> {
  return request(`/jobs/${jobId}/publish`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `job-publish:${jobId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function fetchJobVersions(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobVersionRead[]> {
  return request<JobVersionRead[]>(
    `/jobs/${jobId}/versions`,
    signal ? { signal } : {},
  );
}
