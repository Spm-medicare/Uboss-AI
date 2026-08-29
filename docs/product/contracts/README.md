# Gate 0 Product Contracts

**Status:** Working Draft — not approved  
**Authority:** `PLAN.md` §2, §34 and `docs/delivery/GATE_CONTROLS.md`  
**Gate owner:** Product Designer, with Product Manager and Tech Lead

Gate 0 is a product-contract gate, not a claim that implementation is complete. These documents
turn the approved plan and source workbooks into artifacts that UI, API, database and tests can
share.

| Contract | Purpose | Current state |
|---|---|---|
| `SOURCE_TRACEABILITY.md` | Workbook field → canonical field → UI → API → persistence | Draft baseline extracted; conditional rules and final schema review pending |
| `ACCESS_MODEL.md` | Roles, permission ceiling, sharing, Supervisor handlers and entitlements | Draft; commercial limits and some high-risk approvers pending |
| `LIFECYCLES.md` | Canonical states and legal transitions | Draft; Product approval pending |
| `LAUNCH_DECISIONS.md` | Consequential launch choices with owners and deadlines | Decision register open |
| `FIRST_SLICE_ACCEPTANCE.md` | Clickable prototype and vertical-slice acceptance contract | Draft scenarios ready; Figma and representative reviews pending |

## Approval rule

A document is not approved merely because it exists in Git. Approval requires:

1. every open `DR-*` decision affecting it is resolved;
2. Product, Design and Engineering review the same revision;
3. approver names, date and revision are recorded below; and
4. any later change is versioned and linked to its decision record.

| Role | Approver | Date | Revision | Status |
|---|---|---|---|---|
| Product | — | — | — | Pending |
| Design | — | — | — | Pending |
| Engineering | — | — | — | Pending |

## Non-negotiable controls

- Old code is evidence only; it does not silently define the new contract.
- Workbooks are requirement sources, not screen layouts.
- No workbook meaning is dropped, renamed, merged or conditionally changed without a Product
  decision and an updated mapping.
- Proposed API/storage names remain proposals until the corresponding schema/API review.
- No pending decision may be hidden behind a UI default.

