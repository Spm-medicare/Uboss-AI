# UBOSS AI — Production Incident and On-Call Contract

**Status:** Required before Enterprise Pilot  
**Scope:** Availability, runtime/schedules, integrations, tenant isolation, security, privacy, AI/tool actions and data integrity

## 1. Severity

| Severity | Example | Default handling |
|---|---|---|
| P0 Critical | Cross-tenant exposure, uncontrolled destructive Agent action, broad outage, confirmed serious personal-data breach | Immediate page, Incident Commander, Security/Privacy escalation and containment/kill switch |
| P1 High | Pilot tenant unavailable, schedules broadly missed, material corruption or high-risk integration compromise | Urgent page and coordinated recovery |
| P2 Medium | Bounded degradation with workaround | Working-hours owner and tracked remediation |
| P3 Low | Minor defect without material service risk | Normal product backlog |

Exact acknowledgement/restoration targets are approved with SLOs before pilot.

## 2. Ownership

- Primary/secondary on-call for Web/API, Runtime/Temporal, AI Gateway and Platform.
- Incident Commander owns coordination; technical responders own containment/recovery.
- Security owns security assessment; Privacy Lead/DPO where applicable and Legal own personal-data notification decisions.
- Communications owns customer/status updates; Support owns affected-customer coordination.
- Contact matrix, handoff and escalation policy remain current and are tested.

An Agent may detect, correlate, summarise and propose actions. It cannot close an Incident, erase evidence, decide legal notification or take a critical action without configured human authority.

## 3. Lifecycle

~~~text
Alert/report
→ Acknowledge and classify
→ Assign Incident Commander/responders
→ Preserve evidence/correlation IDs
→ Contain: pause/kill/revoke/isolate
→ Assess tenant/data/obligation impact
→ Communicate on approved cadence
→ Recover through tested rollback/failover/retry
→ Verify service, schedules, data and security
→ Close with evidence
→ Post-incident review and corrective actions
~~~

Record timestamps, severity changes, affected tenants/services/versions, customer impact, actions/actors, decisions, communications and recovery evidence.

## 4. Required alerts

- Tenant-isolation/unauthorised-access or personal-data-breach signal.
- Agent/tool permission violation or abnormal destructive action.
- Runtime/worker outage, stuck workflow or retry storm.
- Missed/late schedules and stuck approvals/outbox/notifications.
- Integration authentication/health failure.
- AI provider error/rate/cost/safety threshold.
- Availability/latency/error-budget breach.
- Backup, restore, replication or storage-integrity failure.

Alerts are actionable, deduplicated, routed to an owner and linked to a runbook. A dashboard without paging/ownership is not an operational control.

## 5. Privacy/security branch

For suspected personal-data impact:

1. Open/link a restricted breach case immediately.
2. Preserve logs, model/tool provenance, affected versions and communications.
3. Contain credentials, integrations, Agents, schedules or tenant access.
4. Assess data categories/principals, regions, processors and impact.
5. Apply the effective legal-requirements register with Privacy/Legal authority.
6. Record notification decisions, approved content, timing and delivery evidence.
7. Complete remediation and recurrence tests before closure.

Do not wait for final root cause before escalation. Do not place sensitive Incident details in unrestricted chat/tickets.

## 6. Recovery, communication and postmortem

- Prefer tested rollback, pause/kill switches, credential revocation, queue isolation and idempotent replay.
- Emergency changes retain actor, reason, diff, validation and retrospective review.
- Communications distinguish confirmed fact, hypothesis, action and next update time.
- Tenant-specific information is not disclosed to unrelated tenants.
- Preserve sent communications and delivery results as evidence.
- Every P0/P1 receives a blameless postmortem: impact, timeline, root/contributing causes, control/alert/runbook failures, corrective actions, owners, due dates and recurrence tests.

## 7. Enterprise Pilot evidence

- Rotation/contact/escalation test and production-like P0 page.
- Commander assignment and service/Agent/integration/schedule kill-switch drill.
- Missed-schedule/stuck-workflow recovery.
- Personal-data-breach tabletop with Privacy/Legal decision evidence.
- Customer/status communication and restore/reconciliation exercise.
- Completed sample P0/P1 postmortem with tracked corrective action.
