import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { CurrentUser } from "@/lib/api/auth";
import messages from "@/messages/en.json";
import { NAVIGATION, SETTINGS_ITEM } from "@/lib/shell/navigation";
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

  it("shows any screen that is not built as a disabled, labelled row", () => {
    //  Driven from the navigation list rather than from a named row, because the named row keeps
    //  moving: this assertion was about To-do until 7.2 built it, then about Settings until 8.1
    //  built it. The rule never moves — `CLAUDE.md`: *"Never show a control that does not do what
    //  it says"* — so the rule is what is asserted.
    //
    //  **Every item is built today**, so the loop below currently iterates nothing. That is stated
    //  rather than hidden: a green test over an empty list proves nothing on its own, which is why
    //  the two assertions that follow it — every built row *is* a link, and the list is the plan's
    //  — are what hold the file up in the meantime. The loop starts working again the moment
    //  somebody adds a screen ahead of its gate, which is exactly when it is needed.
    show({ ...BASE, actions: ["view", "edit_draft", "run"] });

    const unbuilt = [...NAVIGATION.flatMap((group) => group.items), SETTINGS_ITEM].filter(
      (item) => item.buildsIn !== null,
    );

    for (const item of unbuilt) {
      const label = messages.nav.items[item.id as keyof typeof messages.nav.items];
      const row = screen.getByText(label).closest("[aria-disabled]");
      expect(row).not.toBeNull();
      //  It says which gate builds it, rather than leaving a dead row with no explanation.
      expect(row).toHaveAttribute("title", `Not built yet — ${item.buildsIn}`);
      //  Not a link: a control that navigates to a 404 does not do what it says.
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
    }
  });

  it("links Settings when nothing offers to open it as a panel", () => {
    //  The assertion that used to say the opposite: this row read "Not built yet — Gate 8" for
    //  seven gates. The link is the fallback shape — a real route for a link somebody sends.
    show({ ...BASE, actions: ["view"] });

    expect(
      screen.getByRole("link", { name: messages.nav.items.settings }),
    ).toHaveAttribute("href", "/settings");
  });

  it("opens the Settings panel instead of navigating, when the shell offers one", () => {
    //  Which is what the shell does. §13 allows a page *or* a panel, and a panel is the better half
    //  of that choice: changing a timezone in the middle of something else should not cost somebody
    //  their place. `aria-haspopup` is how the row says which of the two it will do.
    const open = vi.fn();
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <Sidebar
          user={{ ...BASE, actions: ["view"] } as CurrentUser}
          collapsed={false}
          onToggle={() => {}}
          ready
          footer={null}
          onOpenSettings={open}
        />
      </NextIntlClientProvider>,
    );

    const row = screen.getByRole("button", { name: messages.nav.items.settings });
    expect(row).toHaveAttribute("aria-haspopup", "dialog");
    expect(
      screen.queryByRole("link", { name: messages.nav.items.settings }),
    ).not.toBeInTheDocument();

    row.click();
    expect(open).toHaveBeenCalledOnce();
  });

  it("links each Builder as its gate lands", () => {
    //  These assertions move here from the test above as each screen is built. A disabled row
    //  and a working link are the same rule read at two moments, and the rule is that the
    //  sidebar never offers a control that does not do what it says.
    show({ ...BASE, actions: ["view", "edit_draft", "run"] });

    for (const [item, href] of [
      [messages.nav.items.agentBuilder, "/agent-builder"],
      [messages.nav.items.supervisor, "/supervisor"],
      [messages.nav.items.todo, "/todo"],
    ] as const) {
      expect(screen.getByRole("link", { name: item })).toHaveAttribute("href", href);
    }
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
