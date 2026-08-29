# Gate 0 Launch Decision Register

**Status:** Open  
**Rule:** No owner or approval is inferred. Recommended defaults are proposals only.

| ID | Decision | Recommended pilot default | Required owner | Needed by | Status |
|---|---|---|---|---|---|
| DR-001 | Company onboarding path | Controlled operator/admin provisioning; self-service post-pilot | Product + Security | Before company journey prototype approval | Decision Required |
| DR-002 | Pilot launch language | English UI; i18n framework from Gate 1; Hindi first optional pack | Product | Gate 0 exit | Decision Required |
| DR-003 | Launch region/residency | India-primary region with documented backup/support transfer boundaries | Security + Privacy + Product | Infrastructure design | Decision Required |
| DR-004 | Commercial plan limits | Named entitlement keys now; numbers approved before billing/pilot | Product + Commercial | Gate 5 limits; final by Gate 8 | Decision Required |
| DR-005 | Pilot identity | Email/password for controlled pilot; enterprise SSO/SCIM sequence by customer | Security + Product | Gate 1 | Decision Required |
| DR-006 | Location/unit model | Tenant-managed Location entity; allow controlled free text only during import mapping | Product + Data | Hierarchy schema | Decision Required |
| DR-007 | First integrations | Claude provider plus email notifications; defer other tools until prioritized use cases | Product + AI + Engineering | Gate 0/1 boundary | Decision Required |
| DR-008 | Objective Publish approval | Independent approver for high-risk/company-wide Objectives; author confirmation otherwise | Product + Governance | Objective prototype | Decision Required |
| DR-009 | Dark mode milestone | Light-first; full dark and reduced-motion acceptance by Gate 8 | Product + Design | Gate 0 exit | Decision Required |
| DR-010 | Supported client baseline | Current Chrome/Edge/Safari; responsive web; complex graph editing desktop-first with mobile list mode | Product + Engineering | Gate 0 exit | Decision Required |
| DR-011 | DPDP responsibilities/contact | Customer/UBOSS role split, privacy contact, DPA and breach authority per privacy contract | Privacy/Legal | Before pilot data | Decision Required |
| DR-012 | Legacy data migration scope | Migrate/Archive/Exclude per `LEGACY_DATA_POLICY.md`; execution disabled until revalidated | Product + Data + Customer | Gate 8 migration rehearsal | Decision Required |

## DR-001 impact on the first slice

The master PLAN says “Create company,” while current ADR 17 implements operator-only tenant
provisioning. Gate 0 must choose one truthful journey:

- **Controlled pilot:** an authorized internal/operator control-plane action creates the tenant;
  the first customer Owner receives invitation/activation. The customer application does not
  pretend self-service exists.
- **Protected admin provisioning:** a separately secured control plane provides the same action.
- **Self-service:** requires abuse controls, identity verification, billing/entitlement bootstrap,
  tenant naming/collision behavior and a separately reviewed global write path.

Until DR-001 is approved, current operator provisioning remains an implementation fact, not a
final product promise.

## Decision record template

For each resolved item, append:

~~~text
Decision ID:
Decision:
Reason:
Rejected alternatives:
Security/privacy/commercial impact:
Approved by:
Approved date:
Artifacts updated:
~~~

