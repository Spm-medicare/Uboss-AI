# UBOSS AI — Privacy and Compliance Contract

**Status:** Gate 0 contract; required before Enterprise Pilot  
**Baseline:** India DPDP with effective-date tracking and jurisdiction-aware extension  
**Boundary:** Product/engineering control specification, not legal advice or an automatic compliance claim

## 1. Authority and responsibility

- Use current official Acts, Rules and commencement notifications plus qualified privacy/legal approval.
- Maintain a versioned requirements register: jurisdiction, provision, effective date, applicability, control, owner, evidence and next review.
- Role is decided per processing purpose and DPA; code must not assume one universal role.
- Customer is normally Data Fiduciary/controller for tenant workforce/workflow data and UBOSS normally its Processor.
- UBOSS may be an independent Data Fiduciary/controller for its own account, security, billing, support and approved telemetry purposes.
- Model, cloud, communication, analytics and support providers processing personal data are governed processors/subprocessors.

Primary official references:

- DPDP Act 2023: https://www.indiacode.nic.in/handle/123456789/22037
- DPDP Rules/enforcement publications: https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digital-Personal-Data-Protection-Rules-2025

## 2. Processing inventory

Every processing activity records:

- Accountable organization and processing role.
- Specific purpose and approved processing basis.
- Data Principal/subject category, data category/classification and source.
- Collection/use systems, recipients/processors and AI access.
- Region, transfer restriction/mechanism and subprocessor chain.
- Retention trigger/period, legal hold and deletion/anonymisation path.
- Owner, effective dates, evidence and review date.

## 3. Notices and consent

- Notices are versioned Draft → independent review/approval → effective/retired definitions with language variants.
- Notice covers itemised data, specific purpose/use, relevant processing basis, recipients/processors, retention summary, rights route and privacy contact.
- Record the applicable notice/purpose/version at collection or material purpose change.
- Consent is recorded only when it is the approved basis: principal, purpose, notice/version, affirmative evidence, channel, language, timestamp and state.
- Withdrawal is as discoverable as grant and creates immutable evidence.
- Legitimate uses/legal duties are modeled separately; the system must not manufacture consent to hide another basis.
- Essential cookies are separated from consent-dependent analytics/marketing according to applicable jurisdiction.

## 4. Data Principal rights and grievance

Supported requests include access; correction, completion and update; erasure; grievance; nomination; and rights introduced by an enabled jurisdiction pack.

~~~text
Submitted
→ Proportionate identity verification
→ Acknowledged and assigned
→ Authorised data discovery
→ Exemption/legal-hold review
→ Fulfil / Partially fulfil / Reject with approved reason
→ Secure delivery and immutable evidence
→ Close / Escalate
~~~

- Requestor cannot approve their own administrative decision.
- SLA, reminders and escalation come from the approved effective-date register.
- Search/export covers database, files, indexes, approved integrations and relevant provider records.
- Responses use secure short-lived delivery and redact other people's data.
- Erasure reconciles live data, files, derived indexes/caches and the approved backup strategy.
- Every exception, legal hold, partial response and rejection records authority, reason and evidence.

## 5. Retention, deletion and legal hold

- Policy is scoped by tenant, data category, purpose, jurisdiction and lifecycle state.
- Define trigger, period, disposal method, exception, backup behavior, owner and review date.
- Execution requires preview and approval where configured.
- Record candidate, excluded/held, deleted/anonymised/archived, failed and reconciled counts with evidence.
- Audit evidence is never silently rewritten; conflicting legal retention duties require an authorised decision.

## 6. Personal-data-breach case

Any suspected personal-data impact opens a restricted breach case linked to the production Incident.

Record:

- Detection/awareness times, reporter, commander and affected tenants/systems/regions.
- Data categories, estimated affected principals and likely impact.
- Containment and evidence preservation.
- Applicable authority/Board and affected-person requirements from the effective-date register.
- Decision log, approved communication, send/delivery evidence and follow-up.
- Remediation, recurrence tests, postmortem and closure approval.

The workflow supports urgent notification clocks, but Privacy/Legal approves applicability, exact timing and wording. An Agent may draft; it cannot decide legal notification or send without authorised approval.

## 7. Processors, subprocessors, DPAs and transfers

Register provider, service/purpose, data categories, role, region/transfer rule, contract/DPA version, safeguards, retention/deletion support, security review, effective dates and customer notice.

New/materially changed subprocessors require risk review, contract approval and configured customer-notice/change workflow before personal data is sent. Provider termination requires export, deletion confirmation and credential/key revocation evidence.

## 8. AI privacy controls

- Minimise and permission-check context before every model call.
- Redact/tokenise fields when exact values are unnecessary.
- Enforce approved provider training, retention, region and DPA settings.
- Record purpose, provider/model policy, prompt/schema version, data categories and tool actions without storing hidden chain-of-thought.
- Propagate correction/erasure to retrieval indexes, caches, stored conversation data and provider records where applicable.
- Evaluate prompt injection, cross-tenant leakage and sensitive-data overexposure.

## 9. Implementation and evidence

Conceptual records include notice/version/purpose, processing activity/basis, consent event, rights request/action, privacy contact, retention policy/execution, legal hold, breach/action/notification, processor/subprocessor/DPA/transfer and evidence links.

Do not implement all future tables in Gate 1. Add only what the current slice processes while preserving these contracts.

Required Gate 8 evidence:

- Approved role/data-flow inventory, DPA and subprocessor register.
- Notice and consent-withdrawal drill where consent applies.
- Access/correction/erasure/grievance request with exception/legal-hold handling.
- Retention execution and deletion reconciliation.
- Personal-data-breach tabletop and notification-delivery evidence.
- Tenant/permission, accessibility/mobile and AI leakage tests.

No UI may show a generic “DPDP/GDPR compliant” badge. Show control status, evidence, gap, owner and review date.

## 10. Legacy reference

Reference only:

- Old `backend/src/uboss_api/privacy/api.py`.
- Old `backend/src/uboss_api/privacy/service.py`.
- Old `backend/src/uboss_api/privacy/schemas.py`.
- Old `runbooks/INCIDENT_RESPONSE.md`.

Revalidate concepts against this architecture and current official requirements; do not copy old code/schema blindly.
