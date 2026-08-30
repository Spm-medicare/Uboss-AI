/**
 * The sidebar, as `PLAN.md` §3 defines it. Nothing here is a design choice.
 *
 * §3 ends with an instruction rather than a suggestion: *"Do not add more permanent MVP menu
 * items. Search, Notifications and Help stay outside the sidebar."* Every navigation product
 * drifts the same way — one item at a time, each defensible on its own — until the sidebar is a
 * list of everything the team built. This file is the list, and adding to it is a change to the
 * plan, not to a component.
 *
 * There is deliberately **no Objective menu**. §3 opens by saying so: all Objective work lives
 * inside the Objective Agent Builder, because an objective is not a place a person goes, it is
 * something they build.
 *
 * `requires` is the *courtesy*, not the boundary. PLAN line 94: *"Menu visibility is role-based;
 * backend permission enforcement remains mandatory."* Hiding an item a person cannot use spares
 * them a refusal they could do nothing about; it is not what stops them, and this file must never
 * be mistaken for the thing that does. `backend/src/uboss/core/permissions.py` is that.
 */

import type { LucideIcon } from "lucide-react";
import {
  Bot,
  ClipboardList,
  LayoutDashboard,
  ListChecks,
  Network,
  Target,
  UserCog,
  Workflow,
} from "lucide-react";

/** The verbs from PLAN §14, mirroring `Action` in the backend. Not a second vocabulary. */
export type Action =
  | "view"
  | "comment"
  | "edit_draft"
  | "publish"
  | "run"
  | "approve"
  | "assign"
  | "schedule"
  | "manage_access"
  | "export"
  | "integrate"
  | "administer"
  | "audit";

export interface NavItem {
  /** Stable key, and the message-catalogue key under `nav.`. */
  id: string;
  href: string;
  icon: LucideIcon;
  /** Hidden unless the session carries this action. The server checks again regardless. */
  requires: Action;
  /**
   * The gate that builds this screen, or `null` once it exists.
   *
   * An item whose screen is not built yet is shown disabled and labelled, never hidden and never
   * linked to a 404. `CLAUDE.md`: *"Never show a control that does not do what it says."* Hiding
   * it instead would be worse — a person would read the absence as "I do not have access", which
   * is a different and untrue statement.
   */
  buildsIn: string | null;
  /** Shown as `01`–`04` beside the four Agents, exactly as §3 numbers them. */
  ordinal?: string;
}

export interface NavGroup {
  /** Message key under `nav.groups.`, or `null` for the unlabelled Agents group. */
  id: string;
  items: NavItem[];
  /** Agents is the one collapsible group in §3. */
  collapsible?: boolean;
}

export const NAVIGATION: NavGroup[] = [
  {
    id: "workspace",
    items: [
      {
        id: "dashboard",
        href: "/dashboard",
        icon: LayoutDashboard,
        requires: "view",
        buildsIn: null,
      },
      {
        id: "hierarchy",
        href: "/hierarchy",
        icon: Network,
        requires: "view",
        buildsIn: null,
      },
    ],
  },
  {
    id: "agents",
    collapsible: true,
    items: [
      {
        id: "objectiveBuilder",
        ordinal: "01",
        href: "/objective-builder",
        icon: Target,
        requires: "edit_draft",
        buildsIn: "Gate 3",
      },
      {
        id: "jobBuilder",
        ordinal: "02",
        href: "/job-builder",
        icon: Workflow,
        requires: "edit_draft",
        buildsIn: "Gate 4",
      },
      {
        id: "agentBuilder",
        ordinal: "03",
        href: "/agent-builder",
        icon: Bot,
        requires: "edit_draft",
        buildsIn: "Gate 5",
      },
      {
        id: "supervisor",
        ordinal: "04",
        href: "/supervisor",
        icon: UserCog,
        requires: "run",
        buildsIn: "Gate 6",
      },
    ],
  },
  {
    id: "governedWork",
    items: [
      {
        id: "todo",
        href: "/todo",
        icon: ListChecks,
        requires: "view",
        buildsIn: "Gate 7",
      },
    ],
  },
];

/**
 * Settings, which §3 puts in the footer beside the avatar and the workspace switcher rather than
 * in the menu itself.
 */
export const SETTINGS_ITEM: NavItem = {
  id: "settings",
  href: "/settings",
  icon: ClipboardList,
  requires: "view",
  buildsIn: "Gate 8",
};

/**
 * Whether this person sees the item at all.
 *
 * `actions` is the *narrowed* set the API returned — already through the company → department →
 * resource → action ceiling. This does no resolution of its own, on purpose: two places that
 * compute permissions are two places that can disagree, and the one that would win is the one
 * printed on the screen.
 */
export function canSee(item: NavItem, actions: readonly string[]): boolean {
  return actions.includes(item.requires);
}

/** The item whose screen the current path is on, longest match first. */
export function activeItem(pathname: string): NavItem | undefined {
  return [...NAVIGATION.flatMap((group) => group.items), SETTINGS_ITEM]
    .filter((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0];
}
