/**
 * The company tree, as the browser calls it.
 *
 * Every function here is a thin wrapper over `request()`, and its whole job is to derive the
 * **idempotency key from the operation** — never from `crypto.randomUUID()` at the call site.
 * That is the difference between a retry the server recognises as a repeat and a retry that
 * creates a second department.
 *
 * The keys below are built from what the operation *is*: the entity and the version it acts on.
 * Retrying "rename unit 41f from version 3" reuses the key; renaming it again afterwards is a
 * different operation on version 4, and gets a different one.
 */

import { request } from "./client";
import { operationKey } from "./idempotency";
import type {
  AssignmentCreate,
  AssignmentEnd,
  OrgUnitCreate,
  OrgUnitMove,
  OrgUnitUpdate,
  PositionCreate,
  PositionUpdate,
  ReportingEdgeCreate,
  RevisionPage,
  TreeRead,
  ValidationIssue,
} from "./contract";

/** What every mutation answers with: the row's id and the version it now holds. */
export interface Written {
  id: string;
  version?: string;
  revision_no?: string;
}

function query(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === false) continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

export function fetchTree(
  options: { asAt?: string; includeArchived?: boolean; signal?: AbortSignal } = {},
): Promise<TreeRead> {
  const path = `/hierarchy${query({
    as_at: options.asAt,
    include_archived: options.includeArchived,
  })}`;
  return request<TreeRead>(path, options.signal ? { signal: options.signal } : {});
}

export function fetchIssues(
  options: { asAt?: string; signal?: AbortSignal } = {},
): Promise<ValidationIssue[]> {
  return request<ValidationIssue[]>(
    `/hierarchy/issues${query({ as_at: options.asAt })}`,
    options.signal ? { signal: options.signal } : {},
  );
}

export function fetchRevisions(
  options: { limit?: number; beforeRevisionNo?: number; signal?: AbortSignal } = {},
): Promise<RevisionPage> {
  return request<RevisionPage>(
    `/hierarchy/revisions${query({
      limit: options.limit ? String(options.limit) : undefined,
      before_revision_no: options.beforeRevisionNo
        ? String(options.beforeRevisionNo)
        : undefined,
    })}`,
    options.signal ? { signal: options.signal } : {},
  );
}

/**
 * Create a department.
 *
 * The key is derived from the parent and the name, so a double-submit of one form creates one
 * department. Creating a genuinely second department with the same name under the same parent
 * would reuse the key — and that is the right answer: it is almost certainly the same mistake,
 * and the caller gets the first one back rather than a duplicate.
 */
export function createUnit(body: OrgUnitCreate): Promise<Written> {
  return request<Written>("/hierarchy/units", {
    method: "POST",
    body,
    idempotencyKey: operationKey("unit-create", body.parent_id ?? "root", body.name),
  });
}

export function updateUnit(id: string, body: OrgUnitUpdate): Promise<Written> {
  return request<Written>(`/hierarchy/units/${id}`, {
    method: "PATCH",
    body,
    idempotencyKey: `unit-update:${id}:v${body.expected_version}`,
    expectedVersion: body.expected_version,
  });
}

export function moveUnit(id: string, body: OrgUnitMove): Promise<Written> {
  return request<Written>(`/hierarchy/units/${id}/move`, {
    method: "POST",
    body,
    idempotencyKey: `unit-move:${id}:v${body.expected_version}`,
    expectedVersion: body.expected_version,
  });
}

export function archiveUnit(id: string, expectedVersion: number): Promise<Written> {
  return request<Written>(`/hierarchy/units/${id}/archive`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `unit-archive:${id}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function createPosition(body: PositionCreate): Promise<Written> {
  return request<Written>("/hierarchy/positions", {
    method: "POST",
    body,
    idempotencyKey: operationKey("position-create", body.org_unit_id, body.title),
  });
}

export function updatePosition(id: string, body: PositionUpdate): Promise<Written> {
  return request<Written>(`/hierarchy/positions/${id}`, {
    method: "PATCH",
    body,
    idempotencyKey: `position-update:${id}:v${body.expected_version}`,
    expectedVersion: body.expected_version,
  });
}

export function archivePosition(id: string, expectedVersion: number): Promise<Written> {
  return request<Written>(`/hierarchy/positions/${id}/archive`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `position-archive:${id}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function assignPerson(
  positionId: string,
  body: AssignmentCreate,
): Promise<Written> {
  return request<Written>(`/hierarchy/positions/${positionId}/assignments`, {
    method: "POST",
    body,
    //  The date is part of the operation: assigning the same person to the same seat from a
    //  different date is a different change, and must not be swallowed as a retry.
    idempotencyKey: `assign:${positionId}:${body.membership_id}:${body.effective_from}`,
  });
}

export function endAssignment(id: string, body: AssignmentEnd): Promise<Written> {
  return request<Written>(`/hierarchy/assignments/${id}`, {
    method: "PATCH",
    body,
    idempotencyKey: `assignment-end:${id}:v${body.expected_version}`,
    expectedVersion: body.expected_version,
  });
}

export function addReportingLine(
  positionId: string,
  body: ReportingEdgeCreate,
): Promise<Written> {
  return request<Written>(`/hierarchy/positions/${positionId}/reporting`, {
    method: "POST",
    body,
    idempotencyKey: `reporting:${positionId}:${body.manager_position_id}:${body.kind}:${body.effective_from}`,
  });
}

/**
 * Undo one recorded change.
 *
 * Keyed on the revision, so a retry undoes it once. Pressing undo twice on the same revision is
 * the same request, not two — and the second one would be refused anyway, because the undo is
 * itself the entity's most recent change by then.
 */
export function undoRevision(revisionId: string): Promise<Written> {
  return request<Written>(`/hierarchy/revisions/${revisionId}/undo`, {
    method: "POST",
    body: {},
    idempotencyKey: `undo:${revisionId}`,
  });
}
