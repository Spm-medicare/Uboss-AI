/**
 * Names for the generated contract.
 *
 * `schema.d.ts` is generated from `backend/openapi.json` and must never be edited by hand — the
 * next regeneration would discard the edit, and until then the compiler would be checking
 * against a contract the server does not honour.
 *
 * Everything the application uses is aliased here, so a component imports `CurrentUser` rather
 * than `components["schemas"]["CurrentUser"]`. If the backend renames a field, this file stops
 * compiling and every use of it does too — which is the entire point.
 *
 * To regenerate, after any route or model change:
 *
 *     cd backend && uv run python -m uboss.export_openapi
 *     cd frontend && npm run generate:api
 *
 * CI fails if either output differs from what is committed.
 */

import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type CurrentUser = Schemas["CurrentUser"];
export type WorkspaceSummary = Schemas["WorkspaceSummary"];
export type SignInResponse = Schemas["SignInResponse"];
export type ChooseWorkspaceResponse = Schemas["ChooseWorkspaceResponse"];
export type SignInRequest = Schemas["SignInRequest"];
export type WorkspaceSelectionRequest = Schemas["WorkspaceSelectionRequest"];
export type SessionSummary = Schemas["SessionSummary"];
export type PasswordStepUpRequest = Schemas["PasswordStepUpRequest"];
export type StepUpResponse = Schemas["StepUpResponse"];

//  The company tree — PLAN §5.
export type TreeRead = Schemas["TreeRead"];
export type OrgUnitRead = Schemas["OrgUnitRead"];
export type PositionRead = Schemas["PositionRead"];
export type PersonInSeat = Schemas["PersonInSeat"];
export type UnitType = Schemas["UnitType"];
export type ReportingKind = Schemas["ReportingKind"];
export type OrgUnitCreate = Schemas["OrgUnitCreate"];
export type OrgUnitUpdate = Schemas["OrgUnitUpdate"];
export type OrgUnitMove = Schemas["OrgUnitMove"];
export type PositionCreate = Schemas["PositionCreate"];
export type PositionUpdate = Schemas["PositionUpdate"];
export type AssignmentCreate = Schemas["AssignmentCreate"];
export type AssignmentEnd = Schemas["AssignmentEnd"];
export type ReportingEdgeCreate = Schemas["ReportingEdgeCreate"];
export type RevisionPage = Schemas["RevisionPage"];
export type RevisionRead = Schemas["RevisionRead"];
export type ValidationIssue = Schemas["ValidationIssue"];

/** The shape of every failure, from `ErrorEnvelope` — PLAN §28. */
export type ErrorEnvelope = Schemas["ErrorEnvelope"];
export type FieldError = Schemas["FieldError"];

export type { components, paths };
