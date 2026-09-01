/**
 * The To-do list, as the browser calls it — §11.
 *
 * **There is no `createTask`.** A task exists because a run reached a human step; the backend has
 * no route to make one, and neither does this. Everything here reads or closes work the runtime
 * already created.
 *
 * Every key is derived from the operation, never `crypto.randomUUID()`: completing task 47 is the
 * same intent whether it is sent once or four times over a bad connection, and a fresh key per
 * attempt would let a retry record a second decision.
 */

import { request } from "./client";
import type {
  TaskCounts,
  TaskDetail,
  TaskKind,
  TaskRead,
  TaskTab,
} from "./contract";
import { operationKey } from "./idempotency";

export interface TaskFilters {
  tab?: TaskTab;
  kind?: TaskKind;
  runId?: string;
  limit?: number;
  signal?: AbortSignal;
}

export async function fetchTasks({
  tab = "mine",
  kind,
  runId,
  limit,
  signal,
}: TaskFilters = {}): Promise<TaskRead[]> {
  const query = new URLSearchParams({ tab });
  if (kind) query.set("kind", kind);
  if (runId) query.set("run_id", runId);
  if (limit) query.set("limit", String(limit));
  return request<TaskRead[]>(`/tasks?${query.toString()}`, {
    ...(signal ? { signal } : {}),
  });
}

export async function fetchTaskCounts(signal?: AbortSignal): Promise<TaskCounts> {
  return request<TaskCounts>("/tasks/counts", { ...(signal ? { signal } : {}) });
}

export async function fetchTask(id: string, signal?: AbortSignal): Promise<TaskDetail> {
  return request<TaskDetail>(`/tasks/${id}`, { ...(signal ? { signal } : {}) });
}

export async function startTask(id: string): Promise<TaskRead> {
  return request<TaskRead>(`/tasks/${id}/start`, {
    method: "POST",
    idempotencyKey: operationKey("task-start", id),
  });
}

export async function completeTask(
  id: string,
  outcome: string,
  note?: string,
): Promise<TaskRead> {
  return request<TaskRead>(`/tasks/${id}/complete`, {
    method: "POST",
    //  The outcome is part of the key: approving and rejecting are two different decisions, and
    //  a key that ignored which one was sent would let a retry of the second replay the first.
    idempotencyKey: operationKey("task-complete", id, outcome),
    body: { outcome, note: note ?? null },
  });
}

export async function declineTask(id: string, reason: string): Promise<TaskRead> {
  return request<TaskRead>(`/tasks/${id}/decline`, {
    method: "POST",
    idempotencyKey: operationKey("task-decline", id),
    body: { reason },
  });
}

export async function delegateTask(
  id: string,
  toMembershipId: string,
  note?: string,
): Promise<TaskRead> {
  return request<TaskRead>(`/tasks/${id}/delegate`, {
    method: "POST",
    idempotencyKey: operationKey("task-delegate", id, toMembershipId),
    body: { to_membership_id: toMembershipId, note: note ?? null },
  });
}

export async function reassignTask(
  id: string,
  toMembershipId: string,
): Promise<TaskRead> {
  return request<TaskRead>(`/tasks/${id}/reassign`, {
    method: "POST",
    idempotencyKey: operationKey("task-reassign", id, toMembershipId),
    body: { to_membership_id: toMembershipId },
  });
}

export async function commentOnTask(id: string, body: string): Promise<void> {
  await request(`/tasks/${id}/comments`, {
    method: "POST",
    //  The text is in the key. Two different comments are two different intents; one key for
    //  "comment on task 47" would make the second one a replay of the first.
    idempotencyKey: operationKey("task-comment", id, body.slice(0, 120)),
    body: { body },
  });
}

export async function attachEvidence(
  id: string,
  fileId: string,
  note?: string,
): Promise<void> {
  await request(`/tasks/${id}/evidence`, {
    method: "POST",
    idempotencyKey: operationKey("task-evidence", id, fileId),
    body: { file_id: fileId, note: note ?? null },
  });
}

export async function followTask(id: string, following: boolean): Promise<void> {
  await request(`/tasks/${id}/follow`, {
    method: following ? "DELETE" : "POST",
    //  Following and unfollowing are two intents, so the key says which — one key for both would
    //  make the second call a replay of the first.
    idempotencyKey: operationKey("task-follow", id, following ? "off" : "on"),
  });
}
