/**
 * The Skill Factory — §39's *"Create private Skill Draft"*, as the browser calls it.
 *
 * Every mutation carries a key derived from the operation, never a fresh uuid: a retry has to
 * reuse it, which is the whole point. The version goes in the body rather than in `If-Match`
 * because these routes take it as `expected_version` — the same contract the other builders' state
 * transitions use.
 *
 * There is no `deleteDraft`. A skill a resolution selected is part of why something happened, so it
 * is archived and kept.
 */

import { request } from "./client";
import type {
  SkillDraft,
  SkillDraftList,
  SkillDraftSummary,
  SkillDraftUpdate,
  SkillTestKind,
  SkillTestResultStatus,
  SkillVersionRef,
} from "./contract";
import { operationKey } from "./idempotency";

export function fetchSkillDrafts(signal?: AbortSignal): Promise<SkillDraftList> {
  return request<SkillDraftList>("/skills/drafts", signal ? { signal } : {});
}

export function fetchSkillDraft(id: string, signal?: AbortSignal): Promise<SkillDraft> {
  return request<SkillDraft>(`/skills/drafts/${id}`, signal ? { signal } : {});
}

export function fetchSkillDraftSummary(
  id: string,
  signal?: AbortSignal,
): Promise<SkillDraftSummary> {
  return request<SkillDraftSummary>(
    `/skills/drafts/${id}/summary`,
    signal ? { signal } : {},
  );
}

export function createSkillDraft(body: {
  name: string;
  purpose?: string | null;
  department?: string | null;
  industry?: string | null;
}): Promise<{ id: string; version: string }> {
  return request("/skills/drafts", {
    method: "POST",
    body,
    idempotencyKey: operationKey("skill-draft-create", body.name),
  });
}

export function saveSkillDraft(id: string, body: SkillDraftUpdate): Promise<SkillDraft> {
  return request<SkillDraft>(`/skills/drafts/${id}`, {
    method: "PUT",
    body,
    //  Keyed on the version being saved *from*: a retry of this save reuses the key, and the next
    //  save is a different operation because the version moved.
    idempotencyKey: operationKey("skill-draft-save", id, body.expected_version),
  });
}

export function writeSkillTest(
  id: string,
  kind: SkillTestKind,
  body: { sample_situation: string | null; expected_result: string | null },
): Promise<SkillDraft> {
  return request<SkillDraft>(`/skills/drafts/${id}/tests/${kind}`, {
    method: "PUT",
    body,
    idempotencyKey: operationKey("skill-test-write", id, kind, body.expected_result ?? ""),
  });
}

export function recordSkillTestResult(
  id: string,
  kind: SkillTestKind,
  body: { status: SkillTestResultStatus; observed: string },
): Promise<SkillDraft> {
  return request<SkillDraft>(`/skills/drafts/${id}/tests/${kind}/result`, {
    method: "POST",
    body,
    idempotencyKey: operationKey("skill-test-result", id, kind, body.status, body.observed),
  });
}

export function nameSkillApprover(
  id: string,
  approverMembershipId: string,
  expectedVersion: number,
): Promise<SkillDraftSummary> {
  return request<SkillDraftSummary>(`/skills/drafts/${id}/approver`, {
    method: "PUT",
    body: {
      approver_membership_id: approverMembershipId,
      expected_version: expectedVersion,
    },
    idempotencyKey: operationKey("skill-approver", id, approverMembershipId, expectedVersion),
  });
}

function transition(
  id: string,
  step: "submit" | "withdraw" | "archive",
  expectedVersion: number,
): Promise<SkillDraftSummary> {
  return request<SkillDraftSummary>(`/skills/drafts/${id}/${step}`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: operationKey(`skill-${step}`, id, expectedVersion),
  });
}

export const submitSkillDraft = (id: string, expectedVersion: number) =>
  transition(id, "submit", expectedVersion);
export const withdrawSkillDraft = (id: string, expectedVersion: number) =>
  transition(id, "withdraw", expectedVersion);
export const archiveSkillDraft = (id: string, expectedVersion: number) =>
  transition(id, "archive", expectedVersion);

export function approveSkillDraft(
  id: string,
  expectedVersion: number,
): Promise<SkillVersionRef> {
  return request<SkillVersionRef>(`/skills/drafts/${id}/approve`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: operationKey("skill-approve", id, expectedVersion),
  });
}
