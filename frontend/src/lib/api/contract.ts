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

//  The Agent — PLAN §9's ten form groups, and the approved workbook's Form 4.
export type AgentCard = Schemas["AgentCard"];
export type AgentList = Schemas["AgentList"];
export type AgentRead = Schemas["AgentRead"];
export type AgentCreate = Schemas["AgentCreate"];
export type AgentUpdate = Schemas["AgentUpdate"];
export type AgentStatus = Schemas["AgentStatus"];
export type AgentAudience = Schemas["AgentAudience"];
export type AgentWorkbookLists = Schemas["AgentWorkbookLists"];
export type AgentStepInput = Schemas["AgentStepInput"];
export type AgentStepRead = Schemas["AgentStepRead"];
export type EscalationRuleInput = Schemas["EscalationRuleInput"];
export type EscalationRuleRead = Schemas["EscalationRuleRead"];
export type IoSchemaInput = Schemas["IoSchemaInput"];
export type IoSchemaRead = Schemas["IoSchemaRead"];
export type KnowledgeSourceInput = Schemas["KnowledgeSourceInput"];
export type KnowledgeSourceRead = Schemas["KnowledgeSourceRead"];
export type ToolInput = Schemas["ToolInput"];
export type ToolRead = Schemas["ToolRead"];
export type ShareInput = Schemas["ShareInput"];
export type ShareRead = Schemas["ShareRead"];
export type SharePrincipal = Schemas["SharePrincipal"];
export type AgentSkillInput = Schemas["SkillInput"];
export type AgentSkillRead = Schemas["SkillRead"];
export type Situation = Schemas["Situation"];

//  Form 4 section C, and the two publish gates §9 names.
export type SandboxTestInput = Schemas["SandboxTestInput"];
export type SandboxTestRead = Schemas["SandboxTestRead"];
export type SandboxTestList = Schemas["SandboxTestList"];
export type SandboxTestKind = Schemas["SandboxTestKind"];
export type SandboxTestStatus = Schemas["SandboxTestStatus"];
export type AgentPublishSummary = Schemas["AgentPublishSummary"];
export type AgentPublishGate = Schemas["AgentPublishGate"];
export type AgentPublishWarning = Schemas["AgentPublishWarning"];
export type AgentVersionCard = Schemas["AgentVersionCard"];
export type AgentVersionList = Schemas["AgentVersionList"];

//  The Skill Registry — PLAN §39. Internal to Agent Builder; there is no route for it.
export type SkillCard = Schemas["SkillCard"];
export type SkillSearchResult = Schemas["SkillSearchResult"];
export type RegistryLists = Schemas["RegistryLists"];
export type RequirementIn = Schemas["RequirementIn"];
export type ResolutionRead = Schemas["ResolutionRead"];
export type CandidateOutcome = Schemas["CandidateOutcome"];
export type GateOutcome = Schemas["GateOutcome"];
export type DecisionCard = Schemas["DecisionCard"];
export type DecisionList = Schemas["DecisionList"];

//  Supervisors — PLAN §10. Two independent scopes: what is watched, and who may control it.
export type SupervisorCard = Schemas["SupervisorCard"];
export type SupervisorList = Schemas["SupervisorList"];
export type SupervisorRead = Schemas["SupervisorRead"];
export type SupervisorCreate = Schemas["SupervisorCreate"];
export type SupervisorUpdate = Schemas["SupervisorUpdate"];
export type SupervisorLists = Schemas["SupervisorLists"];
export type SupervisorKind = Schemas["SupervisorKind"];
export type SupervisorStatus = Schemas["SupervisorStatus"];
export type HandlerRole = Schemas["HandlerRole"];
export type HandlerInput = Schemas["HandlerInput"];
export type HandlerRead = Schemas["HandlerRead"];
export type SupervisedInput = Schemas["SupervisedInput"];
export type SupervisedRead = Schemas["SupervisedRead"];
export type DependencyInput = Schemas["DependencyInput"];
export type DependencyRead = Schemas["DependencyRead"];
export type QualityGateInput = Schemas["QualityGateInput"];
export type QualityGateRead = Schemas["QualityGateRead"];
export type OnFailure = Schemas["OnFailure"];
export type SupervisorEscalationInput = Schemas["EscalationInput"];
export type SupervisorEscalationRead = Schemas["EscalationRead"];
export type NotificationInput = Schemas["NotificationInput"];
export type NotificationRead = Schemas["NotificationRead"];
export type SupervisorScheduleRead = Schemas["SupervisorScheduleRead"];
export type SupervisorScheduleWrite = Schemas["SupervisorScheduleWrite"];

//  §10 group 10 — failure simulation, and the gate PLAN.md names for Gate 6.
export type SimulationInput = Schemas["SimulationInput"];
export type SimulationRead = Schemas["SimulationRead"];
export type SimulationList = Schemas["SimulationList"];
export type SimulationStatus = Schemas["SimulationStatus"];
export type SupervisorPublishSummary = Schemas["SupervisorPublishSummary"];
export type SupervisorGate = Schemas["SupervisorGate"];
export type SupervisorWarning = Schemas["SupervisorWarning"];
export type SupervisorVersionCard = Schemas["SupervisorVersionCard"];
export type SupervisorVersionList = Schemas["SupervisorVersionList"];

//  Sign-in methods, federated identity and account recovery — PLAN §21 and 1.2.6.
export type SignInMethods = Schemas["SignInMethods"];
export type OAuthStart = Schemas["OAuthStart"];
export type OAuthCallback = Schemas["OAuthCallback"];
export type ForgotPassword = Schemas["ForgotPassword"];
export type ForgotPasswordAnswer = Schemas["ForgotPasswordAnswer"];
export type ResetPassword = Schemas["ResetPassword"];
export type AcceptInvite = Schemas["AcceptInvite"];
export type Delivery = Schemas["Delivery"];

//  §11 — the To-do list. Gate 7.2.
export type TaskRead = Schemas["TaskRead"];
export type TaskDetail = Schemas["TaskDetail"];
export type TaskCounts = Schemas["TaskCounts"];
export type TaskComment = Schemas["CommentRead"];
export type TaskEvidence = Schemas["EvidenceRead"];
//  The tabs and the kinds come from the route's own query parameter and the task's `kind`, so a
//  tab the backend does not serve cannot be typed here.
export type TaskTab = NonNullable<
  paths["/api/v1/tasks"]["get"]["parameters"]["query"]
>["tab"];
export type TaskKind = "work" | "input" | "approval";

//  §11's Approvals tab, and the decision behind it — Gate 7.3.
export type ApprovalRead = Schemas["ApprovalRead"];
export type ApprovalCounts = Schemas["ApprovalCounts"];

//  What a schedule actually did — Gate 7.4.
export type FiringRead = Schemas["FiringRead"];

//  §12's bell — Gate 7.5.
export type BellNotification = Schemas["BellNotification"];
export type NotificationCounts = Schemas["NotificationCounts"];
export type NotificationPreference = Schemas["PreferenceRead"];
export type NotificationSettings = Schemas["SettingsRead"];

//  Runs, as the Dashboard reads them — Gate 7.1.
export type RunRead = Schemas["RunRead"];
export type RunDetail = Schemas["RunDetail"];

//  Who can be put in a seat — wider than PersonRef, which is only active members.
export type PlaceablePerson = Schemas["PlaceablePerson"];

//  Adding a colleague so the chart can place somebody new.
export type InvitePerson = Schemas["InvitePerson"];

//  §12's governed Copilot — Gate 7.7. `CopilotAnswer` carries its own sources and, when the
//  question asked for a change, the difference somebody could go and make. There is no
//  corresponding "apply" shape, because there is no route that applies one.
export type CopilotAnswer = Schemas["AnswerRead"];
export type CopilotSource = Schemas["SourceRead"];
export type CopilotPreview = Schemas["PreviewRead"];
export type CopilotChange = Schemas["ChangeRead"];

//  §39's Skill Factory — a private skill, its six tests and the version approval freezes.
export type SkillDraft = Schemas["DraftRead"];
export type SkillDraftList = Schemas["DraftListRead"];
export type SkillDraftSummary = Schemas["DraftSummaryRead"];
export type SkillDraftUpdate = Schemas["DraftUpdate"];
export type SkillDraftCard = Schemas["DraftCard"];
export type SkillRule = Schemas["RuleRead"];
export type SkillRuleInput = Schemas["RuleInput"];
export type SkillTestRead = Schemas["SkillTestRead"];
export type SkillTestKind = Schemas["SkillTestKind"];
export type SkillTestResultStatus = Schemas["SkillResultStatus"];
export type SkillVersionRef = Schemas["SkillVersionRead"];
export type SkillGap = Schemas["GapRead"];
