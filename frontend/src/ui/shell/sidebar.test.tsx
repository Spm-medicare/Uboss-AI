import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { CurrentUser } from "@/lib/api/auth";
import messages from "@/messages/en.json";
import { Sidebar } from "@/ui/shell/sidebar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

/**
 * AS.3 — role-based menu visibility.
 *
 * These test the *courtesy*, and it is worth writing down which is which. PLAN line 94: *"Menu
 * visibility is role-based; backend permission enforcement remains mandatory."* A hidden item
 * spares somebody a refusal they could do nothing about. What stops them is
 * `backend/src/uboss/core/permissions.py`, which is tested separately and does not trust this.
 *
 * So a failure here is a usability bug, never a security one — and a passing suite here is not
 * evidence of a boundary.
 */
const BASE: CurrentUser = {
  membership_id: "00000000-0000-0000-0000-000000000001",
  display_name: "Asha Menon",
  email: "asha@example.test",
  job_title: "Operations lead",
  roles: ["viewer"],
  actions: ["view"],
  workspace_slug: "acme",
  workspace_name: "Acme Industries",
  timezone: "Asia/Kolkata",
  org_node_id: null,
  stepped_up: false,
  session_expires_at: "2026-09-30T00:00:00Z",
};

function show(user: CurrentUser, collapsed = false) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <Sidebar
        user={user}
        collapsed={collapsed}
        onToggle={() => {}}
        ready
        footer={null}
      />
    </NextIntlClientProvider>,
  );
}

describe("Sidebar", () => {
  it("hides the Builders from somebody who cannot edit a draft", () => {
    show(BASE);

    expect(screen.getByText(messages.nav.items.dashboard)).toBeInTheDocument();
    expect(
      screen.queryByText(messages.nav.items.objectiveBuilder),
    ).not.toBeInTheDocument();
    //  And with them the heading. An "Agents" label above nothing promises something that is
    //  not there.
    expect(screen.queryByText(messages.nav.groups.agents)).not.toBeInTheDocument();
  });

  it("shows the Builders to somebody who can edit a draft", () => {
    show({ ...BASE, actions: ["view", "edit_draft"] });

    expect(screen.getByText(messages.nav.items.objectiveBuilder)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.jobBuilder)).toBeInTheDocument();
    //  Supervisor needs `run`, which this person does not have.
    expect(screen.queryByText(messages.nav.items.supervisor)).not.toBeInTheDocument();
  });

  it("does not link a screen that has not been built", () => {
    //  Supervisor needs `run`, so this person has to hold it to see the row at all.
    show({ ...BASE, actions: ["view", "edit_draft", "run"] });

    const supervisor = screen
      .getByText(messages.nav.items.supervisor)
      .closest("[aria-disabled]");
    expect(supervisor).not.toBeNull();
    //  And it says which gate builds it, rather than leaving a dead row with no explanation.
    expect(supervisor).toHaveAttribute("title", "Not built yet — Gate 6");
    //  Not a link: a control that navigates to a 404 does not do what it says.
    expect(
      screen.queryByRole("link", { name: messages.nav.items.supervisor }),
    ).not.toBeInTheDocument();
  });

  it("links the Agent Builder now that Gate 5 has built it", () => {
    //  This assertion moved here from the test above when the screen was built. A disabled row
    //  and a working link are the same rule read at two moments, and the rule is that the
    //  sidebar never offers a control that does not do what it says.
    show({ ...BASE, actions: ["view", "edit_draft"] });

    expect(
      screen.getByRole("link", { name: messages.nav.items.agentBuilder }),
    ).toHaveAttribute("href", "/agent-builder");
  });

  it("links a screen once it exists", () => {
    show({ ...BASE, actions: ["view", "edit_draft"] });

    expect(
      screen.getByRole("link", { name: messages.nav.items.hierarchy }),
    ).toHaveAttribute("href", "/hierarchy");
    expect(
      screen.getByRole("link", { name: messages.nav.items.objectiveBuilder }),
    ).toHaveAttribute("href", "/objective-builder");
    expect(
      screen.getByRole("link", { name: messages.nav.items.jobBuilder }),
    ).toHaveAttribute("href", "/job-builder");
  });

  it("marks the current screen for assistive technology, not only in colour", () => {
    show(BASE);

    expect(
      screen.getByRole("link", { name: messages.nav.items.dashboard }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("keeps every label readable when collapsed to icons", () => {
    show(BASE, true);

    //  The text is hidden visually and kept in the accessible name. An icon-only control with no
    //  name is unusable with a screen reader — `ui/README.md` forbids it outright.
    expect(
      screen.getByRole("link", { name: messages.nav.items.dashboard }),
    ).toBeInTheDocument();
  });
});
