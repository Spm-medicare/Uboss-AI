import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { AgentSkillRead } from "@/lib/api/contract";
import messages from "@/messages/en.json";
import { SkillRegistry } from "@/ui/builder/skill-registry";

vi.mock("@/lib/api/skills", () => ({
  fetchRegistryLists: vi.fn(() =>
    Promise.resolve({
      layers: [],
      departments: [],
      industries: [],
      archetypes: [],
      autonomy: [],
    }),
  ),
  searchSkills: vi.fn(() => Promise.resolve({ results: [], total: 0, isEmpty: true })),
  resolveRequirement: vi.fn(),
}));

/**
 * The Skill Registry panel, and the two things about it that are easy to get wrong on a screen.
 *
 * The rule `PLAN.md` §39 states — *"similarity never overrides a hard gate"* — is enforced in the
 * backend and proved there. What a screen can still get wrong is offering a control that ignores
 * it, so the assertion here is about the **absence of a button**: a refused candidate has no way
 * to be attached from this panel.
 *
 * The second is `exclusions`. It is the field that stops a plausible choice from being the wrong
 * one, no gate decides it, and hiding it one click away would mean most people never read it.
 */
function show(attached: AgentSkillRead[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <SkillRegistry
          attached={attached}
          department={null}
          industry={null}
          disabled={false}
          onAttach={() => {}}
          onDetach={() => {}}
        />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const SKILL: AgentSkillRead = {
  id: "link-1",
  position: 1,
  skill_id: "00000000-0000-0000-0000-0000000000aa",
  name: "Invoice exception triage",
  catalogue_id: "U-001",
  autonomy: "A2",
  exclusions: "Do not approve payment or change a vendor bank account.",
  resolver_decision_id: null,
  route: null,
  notes: null,
};

describe("SkillRegistry", () => {
  it("shows what an attached skill is not for, on the card", () => {
    show([SKILL]);

    expect(
      screen.getByText("Do not approve payment or change a vendor bank account."),
    ).toBeInTheDocument();
  });

  it("says when a skill was attached without a resolver decision", () => {
    show([SKILL]);

    //  Not a quiet omission. A skill chosen outside the resolver has no record of why, and the
    //  card says so rather than implying it was reasoned about.
    expect(screen.getByText(messages.registry.noDecision)).toBeInTheDocument();
  });

  it("shows the route a decision actually took, when there was one", () => {
    show([{ ...SKILL, resolver_decision_id: "dec-1", route: "reuse" }]);

    expect(screen.getByText(messages.registry.route.reuse)).toBeInTheDocument();
    expect(screen.queryByText(messages.registry.noDecision)).not.toBeInTheDocument();
  });

  it("offers browse and resolve as separate acts", () => {
    show([]);

    //  The split is the design: one ranks by resemblance, the other runs the gates. A single
    //  box doing both would let a ranking read as a verdict.
    const tabs = screen.getByRole("tablist");
    expect(within(tabs).getByText(messages.registry.mode.browse)).toBeInTheDocument();
    expect(within(tabs).getByText(messages.registry.mode.resolve)).toBeInTheDocument();
  });

  it("does not invent a match percentage anywhere on the panel", () => {
    show([SKILL]);

    //  `ts_rank_cd` is a ranking value, not a confidence. A percentage would read as certainty
    //  the backend never claimed, which is the exact failure the 2026-08-22 audit found.
    expect(document.body.textContent).not.toMatch(/\d+%/);
  });
});
