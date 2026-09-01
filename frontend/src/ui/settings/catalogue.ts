/**
 * §13's categories, in §13's order — the whole list, including what is not built.
 *
 * ```
 * Personal:                     Workspace/admin:
 * - Profile and timezone/locale  - General and branding/logo
 * - Appearance and reduced motion- People, teams and guests
 * - Notifications and quiet hours- Roles, permissions and sharing
 * - Security, MFA and sessions   - Hierarchy rules
 * - Personal AI defaults         - Objective/Job policy
 *                                - Agent, Supervisor and Claude governance
 *                                - Integrations and credentials health
 *                                - Schedules/calendars
 *                                - Data, privacy, cookies and retention
 *                                - Audit/compliance and SIEM export
 *                                - Billing, usage and entitlements
 *                                - Developer API, keys and webhooks
 * ```
 *
 * ## Why the unbuilt ones are listed
 *
 * The sidebar already answers this question for screens: *"An item whose screen is not built yet is
 * shown disabled and labelled, never hidden and never linked to a 404 … Hiding it instead would be
 * worse — a person would read the absence as 'I do not have access', which is a different and
 * untrue statement."* A Settings page showing four categories would say this product has four
 * settings.
 *
 * So every category appears, and each one either works or says which gate builds it. `built: false`
 * is not a placeholder screen — it is a sentence about what will be there, and nothing on it can be
 * pressed.
 *
 * ## Where `admin` comes from
 *
 * The workspace half is `administer`-shaped work. The flag here decides whether the category is
 * shown as somebody else's to change, not whether the person may change it: every route re-resolves
 * its own permission, because a list sent to a browser is a list the browser can edit.
 */

export interface SettingsCategory {
  /** Stable id — the message key and the URL fragment. */
  id: string;
  /** Personal settings, or the workspace's. §13 splits them and so does the navigation. */
  group: "personal" | "workspace";
  /** False when the screen behind it does not exist yet. Never guessed — see `gate`. */
  built: boolean;
  /** The gate that builds it, for a category that is not built. */
  gate?: string;
  /** True when this is workspace-wide configuration rather than a person's own. */
  admin?: boolean;
}

export const CATEGORIES: readonly SettingsCategory[] = [
  //  Personal — the four that exist, then §13's fifth.
  { id: "profile", group: "personal", built: true },
  { id: "appearance", group: "personal", built: true },
  { id: "notifications", group: "personal", built: true },
  { id: "security", group: "personal", built: true },
  //  "Personal AI defaults within company policy" — there is no company AI policy to sit inside
  //  yet, and a personal default with nothing above it would be a preference pretending to be
  //  governed.
  { id: "ai", group: "personal", built: false, gate: "Gate 8" },

  { id: "general", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "people", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "roles", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "hierarchyRules", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "workPolicy", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "governance", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "integrations", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "schedules", group: "workspace", built: false, gate: "Gate 8", admin: true },
  //  §13's "Data, privacy, cookies and retention" is 8.2's whole subject — DPDP notices, consent,
  //  data-principal requests, retention. Named here so the category exists rather than appearing
  //  the day it is built.
  { id: "privacy", group: "workspace", built: false, gate: "Gate 8.2", admin: true },
  { id: "audit", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "billing", group: "workspace", built: false, gate: "Gate 8", admin: true },
  { id: "developer", group: "workspace", built: false, gate: "Gate 8", admin: true },
];
