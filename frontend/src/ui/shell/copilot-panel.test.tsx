import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CopilotAnswer } from "@/lib/api/contract";
import messages from "@/messages/en.json";
import { CopilotPanel } from "@/ui/shell/copilot-panel";

/**
 * The three states of an answer that a live run cannot reach.
 *
 * `copilot-screen.mjs` drives the real thing in a browser, and it proves the states the running
 * deployment can produce: the intro, an ungrounded answer, and the honest "no model" fallback,
 * which is what this deployment's model account currently returns. It cannot produce a *grounded*
 * answer, an injection notice or a change preview, because all three require a model to answer —
 * and pointing the browser test at a fixture would mean testing a fixture.
 *
 * So the API module is mocked here and the component is driven for real: typed into, submitted,
 * and read back. What is under test is the rule `CLAUDE.md` states plainly — *"never display a
 * value the backend did not return"* — from its other side: **when the backend does return
 * something, the screen must show it, and must show the difference between grounded and not.**
 */
vi.mock("@/lib/api/copilot", () => ({
  askCopilot: vi.fn(),
  SOURCE_KINDS: ["objective", "job", "agent", "supervisor", "org_unit", "position"],
}));

const { askCopilot } = await import("@/lib/api/copilot");
const asked = vi.mocked(askCopilot);

const SOURCE = {
  kind: "objective",
  id: "2c1c8a4e-0000-4000-8000-000000000001",
  label: "Reduce quotation turnaround",
  text: "Quotations out within one working day.",
  href: "/objective-builder/2c1c8a4e-0000-4000-8000-000000000001",
};

function answer(over: Partial<CopilotAnswer> = {}): CopilotAnswer {
  return {
    text: "Quotations are meant to go out within one working day.",
    sources: [SOURCE],
    grounded: true,
    proposal: true,
    model_unavailable: false,
    ...over,
  };
}

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <QueryClientProvider client={client}>
        <CopilotPanel onNavigate={() => {}} />
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

/** Type a question and send it, the way a person does. */
async function ask(question = "why is quotation turnaround slow?") {
  //  `fireEvent` rather than `user-event`, which is not a dependency of this project. It is the
  //  weaker tool — it dispatches one event instead of simulating a person — and it is enough
  //  here: what is under test is what the panel renders from an answer, not the typing.
  fireEvent.change(screen.getByLabelText(messages.copilot.questionLabel), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: messages.copilot.send }));
  await waitFor(() => expect(asked).toHaveBeenCalled());
}

beforeEach(() => {
  asked.mockReset();
});

describe("the Copilot panel", () => {
  it("labels every answer a proposal, grounded or not", async () => {
    asked.mockResolvedValue(answer());
    show();
    await ask();

    //  §18: *"clearly labels proposal versus saved state"*. On every answer, not only on the ones
    //  carrying a change.
    expect(await screen.findByText(messages.copilot.proposalLabel)).toBeInTheDocument();
    expect(screen.getByText(/From 1 record here/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Reduce quotation turnaround/ })).toHaveAttribute(
      "href",
      SOURCE.href,
    );
  });

  it("shows an ungrounded answer as a guess, and calls its list what it is", async () => {
    asked.mockResolvedValue(answer({ grounded: false }));
    show();
    await ask();

    expect(await screen.findByText(messages.copilot.notGrounded)).toBeInTheDocument();
    expect(screen.getByText(messages.copilot.notGroundedWhy)).toBeInTheDocument();
    //  "What matched", not "Sources" — calling these sources would dress a guess as a citation.
    expect(screen.getByText(messages.copilot.matched)).toBeInTheDocument();
    expect(screen.queryByText(messages.copilot.sources)).not.toBeInTheDocument();
  });

  it("surfaces an instruction found inside company text", async () => {
    asked.mockResolvedValue(answer({ injection_noticed: SOURCE.id }));
    show();
    await ask();

    //  Surfaced rather than swallowed: somebody put it there, and the person reading this is the
    //  one who can go and look at whose record it was.
    expect(await screen.findByText(messages.copilot.injectionTitle)).toBeInTheDocument();
    expect(screen.getByText(messages.copilot.injectionBody)).toBeInTheDocument();
  });

  it("shows a proposed change as a difference, with no way to save it", async () => {
    asked.mockResolvedValue(
      answer({
        change: {
          kind: "objective",
          id: SOURCE.id,
          label: "Reduce quotation turnaround",
          href: SOURCE.href,
          changes: [
            {
              field: "expected_result",
              label: "Expected result",
              current: "Quotations out within one working day.",
              proposed: "Quotations out within four working hours.",
            },
          ],
          refused: null,
        },
      }),
    );
    show();
    await ask();

    expect(await screen.findByText(messages.copilot.proposedChange)).toBeInTheDocument();
    //  Both halves of the diff, so a reader can see what would change rather than only what to.
    expect(screen.getByText("Quotations out within one working day.")).toBeInTheDocument();
    expect(screen.getByText("Quotations out within four working hours.")).toBeInTheDocument();
    expect(screen.getByText(messages.copilot.nothingSaved)).toBeInTheDocument();

    //  The only control is a link to the object. Not a save, not a confirm, not an apply.
    expect(
      screen.getByRole("link", { name: new RegExp(messages.copilot.openToChange) }),
    ).toHaveAttribute("href", SOURCE.href);
    expect(screen.queryByRole("button", { name: /save|apply|confirm/i })).not.toBeInTheDocument();
  });

  it("explains a refused change instead of offering a diff", async () => {
    asked.mockResolvedValue(
      answer({
        change: {
          kind: "objective",
          id: SOURCE.id,
          label: "Reduce quotation turnaround",
          href: SOURCE.href,
          changes: [],
          refused: "This is ready to publish, so it is not being edited now.",
        },
      }),
    );
    show();
    await ask();

    expect(await screen.findByText(messages.copilot.cannotChangeTitle)).toBeInTheDocument();
    expect(
      screen.getByText("This is ready to publish, so it is not being edited now."),
    ).toBeInTheDocument();
    expect(screen.queryByText(messages.copilot.openToChange)).not.toBeInTheDocument();
  });

  it("renders a failure as a failure", async () => {
    //  `CLAUDE.md`: an API failure must render a real error and recovery state. Not an empty
    //  answer, and certainly not a fixture.
    asked.mockRejectedValue(new Error("The workspace did not answer."));
    show();
    await ask();

    expect(await screen.findByText("The workspace did not answer.")).toBeInTheDocument();
    expect(screen.queryByText(messages.copilot.proposalLabel)).not.toBeInTheDocument();
  });

  it("does not ask anything for an empty question", async () => {
    show();
    //  The button is disabled until there is something to ask, and Enter on an empty box does
    //  nothing — a blank question answered with the whole workspace is a data export.
    expect(screen.getByRole("button", { name: messages.copilot.send })).toBeDisabled();
    expect(asked).not.toHaveBeenCalled();
  });
});
