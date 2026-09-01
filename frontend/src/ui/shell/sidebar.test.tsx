import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { CurrentUser } from "@/lib/api/auth";
import messages from "@/messages/en.json";
import { Sidebar } from "@/ui/shell/sidebar";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const EMPLOYEE: CurrentUser = {
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

function show(user: CurrentUser, collapsed = false, onOpenSettings?: () => void) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <Sidebar
        user={user}
        collapsed={collapsed}
        onToggle={() => {}}
        ready
        {...(onOpenSettings ? { onOpenSettings } : {})}
      />
    </NextIntlClientProvider>,
  );
}

describe("Sidebar personas", () => {
  it("gives a normal employee only their personal operational workspace", () => {
    show(EMPLOYEE);

    expect(screen.getByText(messages.nav.items.myDashboard)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.myJobAgent)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.mySupervisorAgent)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.myTodo)).toBeInTheDocument();
    expect(screen.queryByText(messages.nav.groups.builders)).not.toBeInTheDocument();
    expect(screen.queryByText(messages.nav.items.hierarchy)).not.toBeInTheDocument();
  });

  it("gives a scoped builder the confirmed admin information architecture", () => {
    show({ ...EMPLOYEE, roles: ["department-admin"], actions: ["view", "edit_draft"] });

    expect(screen.getByText(messages.nav.items.dashboard)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.hierarchy)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.objectiveOptimization)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.agentBuilderSync)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.jobAgents)).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.supervisorAgents)).toBeInTheDocument();
    expect(screen.queryByText("Job Builder")).not.toBeInTheDocument();
  });

  it("keeps Settings as the only footer destination", () => {
    show(EMPLOYEE);
    expect(screen.getByRole("link", { name: messages.nav.items.settings })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
  });

  it("opens Settings as a dialog when the shell supplies the handler", () => {
    const open = vi.fn();
    show(EMPLOYEE, false, open);
    screen.getByRole("button", { name: messages.nav.items.settings }).click();
    expect(open).toHaveBeenCalledOnce();
  });

  it("keeps collapsed controls accessible", () => {
    show(EMPLOYEE, true);
    expect(screen.getByRole("button", { name: messages.nav.expand })).toBeInTheDocument();
    expect(screen.getByText(messages.nav.items.myDashboard)).toHaveClass("sr-only");
  });
});
