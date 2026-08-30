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

//  The safe import — PLAN §5.
export type ImportSummary = Schemas["ImportSummary"];
export type ImportPreview = Schemas["ImportPreview"];
export type ImportRowRead = Schemas["ImportRowRead"];
export type ProposedUnit = Schemas["ProposedUnit"];
export type ImportMappingUpdate = Schemas["ImportMappingUpdate"];

//  Objectives — PLAN §7, and the approved workbook's Form 2.
export type ObjectiveCard = Schemas["ObjectiveCard"];
export type ObjectiveList = Schemas["ObjectiveList"];
export type ObjectiveRead = Schemas["ObjectiveRead"];
export type ObjectiveCreate = Schemas["ObjectiveCreate"];
export type ObjectiveUpdate = Schemas["ObjectiveUpdate"];
export type CurrentStepInput = Schemas["CurrentStepInput"];
export type CurrentStepRead = Schemas["CurrentStepRead"];
export type ObjectiveStatus = Schemas["ObjectiveStatus"];
export type Priority = Schemas["Priority"];
export type Visibility = Schemas["Visibility"];
export type AiAssistance = Schemas["AiAssistance"];
export type WorkbookLists = Schemas["WorkbookLists"];
export type PersonRef = Schemas["PersonRef"];

//  The analysis and the execution graph — PLAN §7.
export type PlanRead = Schemas["PlanRead"];
export type StepRead = Schemas["StepRead"];
export type StepKind = Schemas["StepKind"];
export type StepSource = Schemas["StepSource"];
export type AnalysisRead = Schemas["AnalysisRead"];
export type StageRead = Schemas["StageRead"];
export type Stage = Schemas["Stage"];
export type StageState = Schemas["StageState"];

//  Publishing — PLAN §7's summary and immutable version.
export type PublishSummary = Schemas["PublishSummary"];
export type WarningRead = Schemas["WarningRead"];
export type VersionRead = Schemas["VersionRead"];

//  Jobs — the approved workbook's Form 3 and PLAN §8.
export type JobCard = Schemas["JobCard"];
export type JobList = Schemas["JobList"];
export type JobRead = Schemas["JobRead"];
export type JobCreate = Schemas["JobCreate"];
export type JobUpdate = Schemas["JobUpdate"];
export type JobStepInput = Schemas["JobStepInput"];
export type JobStepRead = Schemas["JobStepRead"];
export type AssignmentRuleInput = Schemas["AssignmentRuleInput"];
export type AssignmentRuleRead = Schemas["AssignmentRuleRead"];
export type JobInputDefinition = Schemas["JobInputDefinition"];
export type JobInputRead = Schemas["JobInputRead"];
export type JobToolDefinition = Schemas["JobToolDefinition"];
export type JobToolRead = Schemas["JobToolRead"];
export type JobStatus = Schemas["JobStatus"];
export type WhoType = Schemas["WhoType"];
export type StepMode = Schemas["StepMode"];
export type AiAccess = Schemas["AiAccess"];
export type InputRequirement = Schemas["InputRequirement"];
export type JobWorkbookLists = Schemas["JobWorkbookLists"];
export type ScheduleRead = Schemas["ScheduleRead"];
export type ScheduleWrite = Schemas["ScheduleWrite"];
export type SchedulePreview = Schemas["SchedulePreview"];
export type JobPublishSummary = Schemas["JobPublishSummary"];
export type JobVersionRead = Schemas["JobVersionRead"];

/** The shape of every failure, from `ErrorEnvelope` — PLAN §28. */
export type ErrorEnvelope = Schemas["ErrorEnvelope"];
export type FieldError = Schemas["FieldError"];

export type { components, paths };
