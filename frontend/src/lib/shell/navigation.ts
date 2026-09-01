/**
 * Product navigation locked by the Phase 1 product contract.
 *
 * Visibility is a courtesy; backend authorization remains the boundary. Job Builder is absent
 * because a published Objective compiles to an internal Job instead of asking a person to enter
 * the same work twice.
 */

import type { LucideIcon } from "lucide-react";
import {
  Bot,
  BriefcaseBusiness,
  ClipboardList,
  LayoutDashboard,
  ListChecks,
  Network,
  Target,
  UserCog,
} from "lucide-react";

import type { CurrentUser } from "@/lib/api/auth";

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
  id: string;
  href: string;
  icon: LucideIcon;
  requires: Action;
  buildsIn: string | null;
  ordinal?: string;
}

export interface NavGroup {
  id: string;
  items: NavItem[];
}

/** Admin and delegated-admin navigation. Server-side scope still narrows every result. */
export const ADMIN_NAVIGATION: NavGroup[] = [
  {
    id: "home",
    items: [
      {
        id: "dashboard",
        href: "/dashboard",
        icon: LayoutDashboard,
        requires: "view",
        buildsIn: null,
      },
    ],
  },
  {
    id: "builders",
    items: [
      {
        id: "hierarchy",
        href: "/hierarchy",
        icon: Network,
        requires: "view",
        buildsIn: null,
      },
      {
        id: "objectiveOptimization",
        href: "/objective-builder",
        icon: Target,
        requires: "edit_draft",
        buildsIn: null,
      },
      {
        id: "agentBuilderSync",
        href: "/agent-builder",
        icon: Bot,
        requires: "edit_draft",
        buildsIn: null,
      },
    ],
  },
  {
    id: "operations",
    items: [
      {
        id: "jobAgents",
        href: "/job-agents",
        icon: BriefcaseBusiness,
        requires: "view",
        buildsIn: null,
      },
      {
        id: "supervisorAgents",
        href: "/supervisor",
        icon: UserCog,
        requires: "view",
        buildsIn: null,
      },
      {
        id: "todo",
        href: "/todo",
        icon: ListChecks,
        requires: "view",
        buildsIn: null,
      },
    ],
  },
];

/** A normal employee sees only their personal operational workspace. */
export const EMPLOYEE_NAVIGATION: NavGroup[] = [
  {
    id: "home",
    items: [
      {
        id: "myDashboard",
        href: "/dashboard",
        icon: LayoutDashboard,
        requires: "view",
        buildsIn: null,
      },
    ],
  },
  {
    id: "operations",
    items: [
      {
        id: "myJobAgent",
        href: "/job-agents",
        icon: BriefcaseBusiness,
        requires: "view",
        buildsIn: null,
      },
      {
        id: "mySupervisorAgent",
        href: "/supervisor",
        icon: UserCog,
        requires: "view",
        buildsIn: null,
      },
      {
        id: "myTodo",
        href: "/todo",
        icon: ListChecks,
        requires: "view",
        buildsIn: null,
      },
    ],
  },
];

/** Compatibility export for screens that do not yet have a session in hand. */
export const NAVIGATION: NavGroup[] = ADMIN_NAVIGATION;

export const SETTINGS_ITEM: NavItem = {
  id: "settings",
  href: "/settings",
  icon: ClipboardList,
  requires: "view",
  buildsIn: null,
};

/**
 * Temporary persona selector until `/auth/me` returns explicit module capabilities. Possessing a
 * design, publishing, assignment, access or audit action selects the scoped admin workspace.
 */
export function hasAdminWorkspace(user: Pick<CurrentUser, "actions">): boolean {
  const adminActions = new Set([
    "edit_draft",
    "publish",
    "assign",
    "schedule",
    "manage_access",
    "administer",
    "audit",
  ]);
  return user.actions.some((action) => adminActions.has(action));
}

export function navigationFor(user: Pick<CurrentUser, "actions">): NavGroup[] {
  return hasAdminWorkspace(user) ? ADMIN_NAVIGATION : EMPLOYEE_NAVIGATION;
}

export function canSee(item: NavItem, actions: readonly string[]): boolean {
  return actions.includes(item.requires);
}

export function activeItem(
  pathname: string,
  navigation: NavGroup[] = NAVIGATION,
): NavItem | undefined {
  return [...navigation.flatMap((group) => group.items), SETTINGS_ITEM]
    .filter((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0];
}
