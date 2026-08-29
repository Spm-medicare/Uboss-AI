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

/** The shape of every failure, from `ErrorEnvelope` — PLAN §28. */
export type ErrorEnvelope = Schemas["ErrorEnvelope"];
export type FieldError = Schemas["FieldError"];

export type { components, paths };
