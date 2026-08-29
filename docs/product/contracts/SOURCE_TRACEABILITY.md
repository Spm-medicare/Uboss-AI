# Source Workbook Traceability

**Status:** Working Draft — not approved  
**Last audited:** 2026-08-29  
**Scope:** source fields required to begin Gate 0 UI/API/schema design

## 1. Source precedence and reconciliation

| Area | Primary requirement source | Reconciliation decision |
|---|---|---|
| Hierarchy | `UBOSS_Complete_Builder_Forms_Organogram (1).xlsx`, Form 1 | Use the stronger unique Position ID and Reports-to Position ID contract |
| Objective | `UBOSS_Agent_Builder_Forms.xlsx`, Form 2 | Preserve all header and repeatable workflow-step meaning |
| Job | `UBOSS_Agent_Builder_Forms.xlsx`, Form 3 | Preserve all header fields and all 16 repeatable step fields |
| Agent | `UBOSS_Agent_Builder_Forms.xlsx`, Form 4 | Preserve design, control, escalation and sandbox-test meaning |
| Skill Registry | `Universal_Enterprise_Skill_Catalog_IF_THEN (1).xlsx` | Seed/catalogue contract is governed separately by `docs/product/SKILL_REGISTRY.md` |

The two builder workbooks agree on Forms 2–4. The Organogram workbook adds a self-reference
dropdown and clearer manager Position ID guidance to Form 1. That additional integrity is kept.

## 2. Mapping conventions

- `Draft` API/storage names below are proposed canonical names, not an implemented-schema claim.
- Header values belong to the aggregate; repeatable rows belong to child records.
- `*` in the workbook means required. Conditional requirements still need Product review where
  the workbook only supplies a dropdown but no explicit condition.
- Reference fields use stable UUIDs in API/storage even when the UI shows a person, role,
  department, position or Agent label.

## 3. Hierarchy mapping

### 3.1 Header

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence | Rule |
|---|---|---|---|---|---|
| Organization Name * | Company name | Text input | `company.name` | `tenants.name` | Required |
| Business Unit / Site | Business unit/site | Search/select or text | `hierarchy.businessUnitName` | `hierarchies.business_unit_name` | Optional until multi-site decision |
| Prepared By * | Prepared by | Authenticated user display | `hierarchy.preparedByUserId` | `hierarchies.prepared_by_user_id` | Required; server-derived where possible |
| Organization Head / Top Position * | Root position | Position selector | `hierarchy.rootPositionId` | `hierarchies.root_position_id` | Required before Publish |
| Date * | Effective date | Date input | `hierarchy.effectiveDate` | `hierarchies.effective_date` | Required |
| Chart Direction | Chart direction | Segmented select | `hierarchy.chartDirection` | `hierarchies.chart_direction` | `TOP_TO_BOTTOM` or `LEFT_TO_RIGHT` |
| Total Levels | Level count | Read-only computed value | `hierarchy.levelCount` | Derived, not client-authored | Computed from tree |
| Total Positions | Position count | Read-only computed value | `hierarchy.positionCount` | Derived, not client-authored | Computed from active draft/version |
| Show Vacant Positions | Show vacant | Switch | `view.showVacantPositions` | User/view preference unless export setting | Must not delete/hide source records |

### 3.2 Repeatable position row

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence | Rule |
|---|---|---|---|---|---|
| Sr. No. | Display order | Drag/reorder + number | `position.sortOrder` | `hierarchy_positions.sort_order` | Server normalizes |
| LEVEL | Tree depth | Read-only badge | `position.level` | Derived/cache only | Levels 1–10 in workbook; product tree must not assume 10 is permanent maximum |
| Position ID | Position reference code | Text input | `position.referenceCode` | `hierarchy_positions.reference_code` | Required and unique within hierarchy version |
| WHO — Person Name | Occupant | User/person selector | `position.occupantUserId` | `position_assignments.user_id` | Blank allowed for vacant/proposed positions |
| WHAT — Designation / Role | Position title | Text/role selector | `position.title` | `hierarchy_positions.title` | Required before Publish |
| WHERE — Department / Function | Department/function | Department selector | `position.departmentId` | `hierarchy_positions.department_id` | Required before Publish |
| REPORTS TO — Position ID / Position / Person | Parent position | Tree position selector | `position.parentPositionId` | `hierarchy_positions.parent_position_id` | Root only may be blank; no cycle/self-parent |
| Reporting Type | Reporting relationship | Select | `position.reportingType` | `hierarchy_positions.reporting_type` | Direct, Dotted-Line, Functional, Project, Temporary |
| Location / Unit | Location/unit | Search/select or text | `position.locationId` / `locationName` | `hierarchy_positions.location_id` or controlled text | Final location model is `DR-006` |
| WHEN — Effective From | Effective from | Date input | `position.effectiveFrom` | `hierarchy_positions.effective_from` | Required for Published version |
| Position Status | Position status | Select | `position.status` | `hierarchy_positions.status` | Filled, Vacant, Proposed, Inactive |
| INPUT — Source | Evidence source | Select + evidence link | `position.sourceType` | `hierarchy_positions.source_type` | HRMS, ERP, Excel, approved org chart, management record, other |
| Notes | Notes | Multiline text | `position.notes` | `hierarchy_positions.notes` | Optional; classified/retained as tenant content |

## 4. Objective mapping

### 4.1 Header

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence | Rule |
|---|---|---|---|---|---|
| Objective Name * | Objective name | Text input | `objective.name` | `objectives.name` | Required |
| Department * | Owning department | Hierarchy selector | `objective.departmentId` | `objectives.department_id` | Required and tenant-bound |
| Objective Owner * | Objective owner | Eligible user selector | `objective.ownerUserId` | `objectives.owner_user_id` | Required and active membership |
| Expected Final Result * | Expected result | Multiline outcome input | `objective.expectedResult` | `objective_versions.expected_result` | Required |
| Current Workload | Current workload | Number input | `objective.currentWorkload.value` | `objective_versions.current_workload_value` | Optional, non-negative |
| Unit | Workload unit | Select | `objective.currentWorkload.unit` | `objective_versions.current_workload_unit` | Required when workload value exists |
| Target Completion Time | Target duration | Number input | `objective.targetDuration.value` | `objective_versions.target_duration_value` | Optional, positive |
| Unit | Target time unit | Select | `objective.targetDuration.unit` | `objective_versions.target_duration_unit` | Required when target duration exists |
| Prepared By | Prepared by | Authenticated user display | `objective.preparedByUserId` | `objective_versions.prepared_by_user_id` | Server-derived |
| Date | Prepared date | Date display/input | `objective.preparedDate` | `objective_versions.prepared_date` | Default current tenant date; editable only by policy |

### 4.2 Existing workflow step

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence |
|---|---|---|---|---|
| Step | Step order | Reorder control | `step.sortOrder` | `objective_workflow_steps.sort_order` |
| WHO — Person Name | Current performer | Person selector | `step.performerUserId` | `objective_workflow_steps.performer_user_id` |
| WHO — Role | Current performer role | Role selector/text | `step.performerRoleId` / `performerRoleName` | `objective_workflow_steps.performer_role_id/name` |
| WHEN — Trigger | Trigger | Select + other text | `step.trigger` | `objective_workflow_steps.trigger` |
| WHEN — Frequency | Frequency | Select + schedule detail | `step.frequency` | `objective_workflow_steps.frequency` |
| WHAT — Exact Work | Exact current work | Multiline text | `step.exactWork` | `objective_workflow_steps.exact_work` |
| INPUT — What Is Used | Input | Repeatable typed input | `step.inputs[]` | `objective_step_inputs` |
| INPUT — Received From | Input source party | Person/team/system selector | `step.inputs[].receivedFrom` | `objective_step_inputs.received_from_*` |
| WHERE — Work Is Done | Work location/system | Select + other text | `step.workLocation` | `objective_workflow_steps.work_location` |
| OUTPUT — What Is Produced | Output | Typed output | `step.output` | `objective_workflow_steps.output` |
| OUTPUT — Sent To | Output destination | Person/team/system selector | `step.outputDestination` | `objective_workflow_steps.output_destination_*` |
| Time Taken | Current duration | Duration input | `step.duration` | `objective_workflow_steps.duration_*` |
| Current Problem | Current problem | Select + detail | `step.currentProblem` | `objective_workflow_steps.current_problem` |
| Approval | Current approval | Select + authority detail | `step.approval` | `objective_workflow_steps.approval_*` |

## 5. Job mapping

### 5.1 Header

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence | Rule |
|---|---|---|---|---|---|
| Objective Name | Parent Objective | Published Objective/version selector | `job.objectiveVersionId` | `jobs.objective_version_id` | Required |
| Department | Owning department | Inherited/read-only with authorized override | `job.departmentId` | `jobs.department_id` | Tenant and scope checked |
| Job ID / Name * | Job name/reference | Text inputs | `job.name`, `job.referenceCode` | `jobs.name/reference_code` | Name required; reference generated if absent |
| Job Owner * | Job owner | Eligible user selector | `job.ownerUserId` | `jobs.owner_user_id` | Required |
| Current Person * | Current performer | Person selector | `job.currentPerformerUserId` | Draft discovery data | Required for workbook import; may become WHO rule |
| Role * | Current role | Role selector | `job.currentPerformerRoleId` | Draft discovery data | Required for workbook import |
| Trigger * | Primary trigger | Trigger builder | `job.trigger` | `job_versions.trigger_config` | Required |
| Frequency * | Frequency | Schedule/frequency builder | `job.frequency` | `job_versions.frequency_config` | Required when trigger repeats |
| High-Level Work * | Purpose/work | Multiline text | `job.purpose` | `job_versions.purpose` | Required |
| Job Start Requirement | Start conditions | Condition builder | `job.startRequirements[]` | `job_start_requirements` | Optional unless policy says otherwise |
| Job Completion Evidence | Completion evidence | Evidence rule builder | `job.completionEvidence[]` | `job_completion_evidence_rules` | Required before Publish |
| Normal Completion Time | Completion duration | Duration input | `job.normalDuration.value` | `job_versions.normal_duration_value` | Optional, positive |
| Time Unit | Duration unit | Select | `job.normalDuration.unit` | `job_versions.normal_duration_unit` | Required with duration |

### 5.2 Repeatable Job step — all 16 source fields

| Workbook field | Canonical field | UI card/control | Draft API property | Draft persistence |
|---|---|---|---|---|
| Step | Step order | Step card reorder | `step.sortOrder` | `job_steps.sort_order` |
| WHO — Person Name | Person assignment | WHO repeatable rule | `step.who[].userId` | `job_step_assignments` |
| WHO — Role | Role assignment | WHO repeatable rule | `step.who[].roleId` | `job_step_assignments` |
| WHEN — Trigger | Step trigger | WHEN card | `step.when.trigger` | `job_steps.trigger_config` |
| WHEN — Frequency | Step frequency | WHEN card | `step.when.frequency` | `job_steps.frequency_config` |
| WHAT — Exact Work | Exact work | Purpose/action card | `step.exactWork` | `job_steps.exact_work` |
| INPUT — Exact Input | Typed input | INPUT repeatable card | `step.inputs[].description` | `job_step_inputs.description` |
| WHERE — Input Is Found | Input location/source | INPUT source control | `step.inputs[].source` | `job_step_inputs.source_config` |
| HOW — Exact Method | Exact method | Method card/editor | `step.method` | `job_steps.method` |
| WHERE — Work Is Performed | Work system/location | Tool/location control | `step.workLocation` | `job_steps.work_location_config` |
| Rule / Formula / Check | Rule/check | Rule builder | `step.rules[]` | `job_step_rules` |
| Output | Typed output | Output card | `step.outputs[]` | `job_step_outputs` |
| Output Destination | Output destination | Output destination control | `step.outputs[].destination` | `job_step_outputs.destination_config` |
| Approval | Approval requirement | Approval card | `step.approval` | `job_step_approval_rules` |
| If Missing / Wrong | Exception behavior | Failure/exception card | `step.onInvalidInput` | `job_steps.invalid_input_policy` |
| Time | Step SLA/duration | SLA/time card | `step.sla` | `job_steps.sla_config` |

## 6. Agent mapping

### 6.1 Header

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence |
|---|---|---|---|---|
| Agent Name * | Agent name | Text input | `agent.name` | `agents.name` |
| Objective | Objective version | Read-only/selector | `agent.objectiveVersionId` | `agents.objective_version_id` |
| Job | Job version | Published Job version selector | `agent.jobVersionId` | `agents.job_version_id` |
| Agent Owner * | Agent owner | Eligible user selector | `agent.ownerUserId` | `agents.owner_user_id` |
| Trigger | Trigger | Inherited/configured trigger | `agent.trigger` | `agent_versions.trigger_config` |
| Main Approver * | Main approver | Approver selector | `agent.mainApproverUserId` | `agent_versions.main_approver_user_id` |
| Completion Time | Completion SLA | Duration input | `agent.completionSla` | `agent_versions.completion_sla_*` |
| Frequency | Frequency | Schedule summary/config | `agent.frequency` | `agent_versions.frequency_config` |
| Error Escalation To * | Error escalation | User/team/role selector | `agent.errorEscalationTarget` | `agent_versions.error_escalation_target` |

### 6.2 Design confirmation step

| Workbook field | Canonical field | UI control | Draft API property | Draft persistence |
|---|---|---|---|---|
| Step | Step order | Reorder control | `step.sortOrder` | `agent_steps.sort_order` |
| Input Used | Input binding | Input binding card | `step.inputBindings[]` | `agent_step_input_bindings` |
| Input Source | Input source | Source selector | `step.inputBindings[].source` | `agent_step_input_bindings.source_config` |
| Tool / System | Tool connection | Tool permission card | `step.toolBindingId` | `agent_step_tool_bindings` |
| Agent Action | Agent action/instruction | Instruction editor | `step.action` | `agent_steps.action` |
| Output | Output | Output schema card | `step.outputSchema` | `agent_steps.output_schema` |
| Output Destination | Output destination | Destination selector | `step.outputDestination` | `agent_steps.output_destination` |
| Approval | Approval timing/rule | Approval card | `step.approvalRule` | `agent_step_approval_rules` |
| Agent Must Never Do | Prohibited actions | Restriction list | `step.prohibitedActions[]` | `agent_step_restrictions` |

### 6.3 Error/escalation and sandbox tests

The workbook explicitly covers mandatory input missing, unclear information and conflicting
information, followed by required Agent action and escalation target. Each becomes a structured
exception policy, not only prompt text. Sandbox test rows preserve scenario, expected behavior,
actual evidence and status (`NOT_RUN`, `PASS`, `FAIL`, `BLOCKED`).

## 7. Controlled dropdown catalogue

The source workbook supplies controlled lists for Department, Trigger, Frequency, Where, Problem,
Approval, Workload Unit, Time Unit, Input Type, Method, Input Status, Approval Timing, Missing
Action, Conflict Action, Failure Action, Output Format, Permission, Test Status, Yes/No, Review
Decision, Hierarchy Level, Reporting Type, Position Status, Hierarchy Input Source and Chart
Direction.

These values seed tenant-aware reference data or canonical enums. `Other` always requires a
companion detail field. Labels may be translated; stable codes may not. Department values are
starter suggestions, not a fixed global enum, because the actual hierarchy is company-owned.

## 8. Open traceability work

- Confirm every Form 4 row after the visible workbook section, including all review/test columns.
- Convert each dropdown label to a stable language-neutral code and record aliases.
- Resolve `DR-006` for location/unit modeling.
- Review every conditional required rule with Product; workbook `allowBlank` is not sufficient
  evidence of business optionality.
- Replace draft persistence names only through an approved schema review, keeping this mapping
  updated in the same change.

