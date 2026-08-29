# UBOSS AI — Legacy Data Migration Policy

## Principle

Old code and schema are reference-only. Client-owned data is evaluated independently and is never silently discarded or bulk-copied.

## Classification

### Candidate for migration

- Valid company/workspace identity.
- Real users, teams and membership mappings.
- Valid hierarchy units, positions, assignments and reporting edges.
- Real Objectives, Jobs and Agents.
- Published versions and active schedules when verifiable.
- Approvals, evidence and governance-relevant audit.
- Universal Skill Catalogue and IF-THEN rules.

### Archive rather than transform

- Audit/events that cannot be safely mapped without altering meaning.
- Historical versions with incomplete new-schema fields.
- Old outputs needed for legal/business reference but not active execution.

### Exclude

- Demo/test/seed records.
- Mock or simulated approvals/runs.
- Placeholder/broken/duplicate records.
- Development accounts/passwords.
- API keys, tokens, credentials and secrets.
- Unverified generated output presented without evidence.

## Migration sequence

1. Freeze source snapshot and record checksums.
2. Inventory tables/files and record counts.
3. Classify each dataset: Migrate, Archive, Exclude, Pending decision.
4. Map source fields/IDs to canonical vNext contracts.
5. Run dry import into staging.
6. Validate tenant, relationships, versions and permissions.
7. Reconcile expected versus landed counts and hashes/samples.
8. Review exceptions with business/data owner.
9. Pilot one tenant.
10. Approve cutover and record cutover timestamp.
11. Run controlled import with idempotency.
12. Reconcile again and retain rollback package.

## Audit preservation

- Never rewrite old actors/timestamps to look like new events.
- Preserve original source ID, timestamp and provenance.
- If mapped, label event source as LEGACY_IMPORT.
- If not safely mappable, retain signed/read-only archive with search/export controls.
- New append-only ledger begins at recorded cutover.

## Activation rule

Migrated Drafts remain Draft. Migrated Agents/Schedules do not execute until owner, permissions, credentials, versions and policy are revalidated.

## Required migration report

- Source snapshot and checksum.
- Per-entity expected/imported/skipped/error counts.
- ID mapping.
- Relationship/orphan results.
- Audit/archive disposition.
- Exclusions and reasons.
- Approver and timestamp.
- Rollback reference.
