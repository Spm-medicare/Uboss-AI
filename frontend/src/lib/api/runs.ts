/**
 * Runs, as the browser reads them — Gate 7.1's executor, seen from the Dashboard.
 *
 * Read-only here. Starting and cancelling a run happen from a Job, and a Dashboard that could
 * start one would be a Dashboard that runs a governed method from a summary screen.
 */

import { request } from "./client";
import type { RunDetail, RunRead } from "./contract";

export async function fetchRuns(
  limit = 8,
  signal?: AbortSignal,
): Promise<RunRead[]> {
  return request<RunRead[]>(`/runs?limit=${limit}`, {
    ...(signal ? { signal } : {}),
  });
}

/** One run, with its steps and what happened. */
export function fetchRun(id: string, signal?: AbortSignal): Promise<RunDetail> {
  return request<RunDetail>(`/runs/${id}`, signal ? { signal } : {});
}

/**
 * Everything recorded about a run — Gate 7.6's document.
 *
 * Typed by hand rather than from the generated schema because the route returns a free-shaped
 * object: it is an assembled account rather than one table's row, and pinning it in the OpenAPI
 * schema would freeze a document that is meant to gain sections as the runtime learns to record
 * more. The names here match `runtime/evidence.py` exactly.
 */
export interface RunEvidence {
  run: {
    id: string;
    state: string;
    trigger: string;
    job_id: string;
    job_name: string | null;
    job_version_id: string;
    job_version_no: number | null;
    started_by: string | null;
    started_at: string | null;
    finished_at: string | null;
    failure_detail: string | null;
    correlation_id: string | null;
  };
  steps: {
    id: string;
    position: number;
    title: string;
    mode: string;
    state: string;
    attempt: number;
    started_at: string | null;
    finished_at: string | null;
    result: Record<string, unknown> | null;
    failure_detail: string | null;
  }[];
  events: {
    kind: string;
    detail: Record<string, unknown>;
    occurred_at: string | null;
    run_step_id: string | null;
    correlation_id: string | null;
  }[];
  tasks: {
    id: string;
    title: string;
    state: string;
    assignee: string | null;
    outcome: string | null;
    outcome_note: string | null;
    completed_by: string | null;
    completed_at: string | null;
    comments: { author: string | null; body: string; written_at: string | null }[];
    evidence_file_ids: string[];
  }[];
  approvals: {
    id: string;
    task_id: string;
    state: string;
    requested_by: string | null;
    decided_by: string | null;
    reason: string | null;
    decided_at: string | null;
  }[];
  outputs: {
    position: number;
    name: string;
    destination: string | null;
    format: string | null;
    value_text: string | null;
    file_id: string | null;
    run_step_id: string | null;
    produced_at: string | null;
  }[];
  model_calls: {
    task_kind: string;
    provider: string;
    model: string;
    outcome: string;
    detail: string | null;
    input_tokens: number | null;
    output_tokens: number | null;
    latency_ms: number | null;
    by: string | null;
    occurred_at: string | null;
    run_step_id: string | null;
  }[];
  tool_calls: unknown[];
  /** False until Gate 8 wires the integrations. Distinct from "this run used no tools". */
  tool_calls_available: boolean;
}

export function fetchRunEvidence(id: string, signal?: AbortSignal): Promise<RunEvidence> {
  return request<RunEvidence>(`/runs/${id}/evidence`, signal ? { signal } : {});
}
