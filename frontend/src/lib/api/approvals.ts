/**
 * Approvals, as the browser calls them — §11's Approvals tab.
 *
 * **There is no `createApproval`.** An approval is raised when a run reaches an approval step;
 * the backend has no route to make one, and neither does this.
 *
 * `decide` goes through the approvals route rather than the task's `complete`, because that route
 * is what enforces separation of duty against *this* approval's requester. Both write the same
 * three records — the approval, the task and the run step — in one transaction.
 */

import { request } from "./client";
import type { ApprovalCounts, ApprovalRead } from "./contract";
import { operationKey } from "./idempotency";

export interface ApprovalFilters {
  /** Only the ones addressed to me — including any escalated to me. */
  mine?: boolean;
  state?: string;
  runId?: string;
  limit?: number;
  signal?: AbortSignal;
}

export async function fetchApprovals({
  mine = true,
  state,
  runId,
  limit,
  signal,
}: ApprovalFilters = {}): Promise<ApprovalRead[]> {
  const query = new URLSearchParams({ mine: String(mine) });
  if (state) query.set("state", state);
  if (runId) query.set("run_id", runId);
  if (limit) query.set("limit", String(limit));
  return request<ApprovalRead[]>(`/approvals?${query.toString()}`, {
    ...(signal ? { signal } : {}),
  });
}

export async function fetchApprovalCounts(
  signal?: AbortSignal,
): Promise<ApprovalCounts> {
  return request<ApprovalCounts>("/approvals/counts", {
    ...(signal ? { signal } : {}),
  });
}

export async function decideApproval(
  id: string,
  state: string,
  reason?: string,
): Promise<ApprovalRead> {
  return request<ApprovalRead>(`/approvals/${id}/decide`, {
    method: "POST",
    //  The decision is part of the key: approving and rejecting are two different intents, and a
    //  key that ignored which was sent would let a retry of one replay the other.
    idempotencyKey: operationKey("approval-decide", id, state),
    body: { state, reason: reason ?? null },
  });
}

export async function escalateApproval(
  id: string,
  toMembershipId?: string,
  note?: string,
): Promise<ApprovalRead> {
  return request<ApprovalRead>(`/approvals/${id}/escalate`, {
    method: "POST",
    idempotencyKey: operationKey("approval-escalate", id, toMembershipId ?? "note"),
    body: { to_membership_id: toMembershipId ?? null, note: note ?? null },
  });
}
