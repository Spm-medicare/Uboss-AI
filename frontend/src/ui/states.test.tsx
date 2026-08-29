import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "@/lib/api/errors";
import messages from "@/messages/en.json";
import { QueryStates } from "@/ui/states";

/**
 * The one rule these states exist to enforce.
 *
 * `CLAUDE.md`: "Never report success for a request that failed. An API failure must render a real
 * error and recovery state; legitimate zero data must render an empty state." The 2026-08-22
 * audit found the previous build breaking exactly this, so it is pinned by a test rather than by
 * a review comment.
 */
function show(ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

describe("QueryStates", () => {
  it("renders the error, not an empty state, when a request fails", () => {
    show(
      <QueryStates
        isPending={false}
        error={new NetworkError()}
        isEmpty
        emptyTitle="Nothing here"
      >
        <p>rows</p>
      </QueryStates>,
    );

    //  Both flags were set. The failure wins — "there is nothing here" would be a lie.
    expect(screen.getByText(messages.states.offlineTitle)).toBeInTheDocument();
    expect(screen.queryByText("Nothing here")).not.toBeInTheDocument();
  });

  it("renders the empty state only when the request succeeded", () => {
    show(
      <QueryStates isPending={false} error={null} isEmpty emptyTitle="Nothing here">
        <p>rows</p>
      </QueryStates>,
    );

    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.queryByText("rows")).not.toBeInTheDocument();
  });

  it("shows a refusal without saying anything about the resource", () => {
    show(
      <QueryStates
        isPending={false}
        error={
          new ApiError(403, {
            code: "forbidden",
            message: "objective 41f is restricted",
            field_errors: [],
            correlation_id: "c-1",
            retryable: false,
          })
        }
      >
        <p>rows</p>
      </QueryStates>,
    );

    expect(
      screen.getByText(messages.states.deniedTitle),
    ).toBeInTheDocument();
    //  The server's detail is not repeated: a refusal that explains itself confirms the thing
    //  exists, which is what the person was not allowed to learn.
    expect(screen.queryByText(/41f/)).not.toBeInTheDocument();
  });

  it("waits before deciding anything", () => {
    show(
      <QueryStates isPending error={null} isEmpty emptyTitle="Nothing here">
        <p>rows</p>
      </QueryStates>,
    );

    expect(screen.getByText(messages.states.loading)).toBeInTheDocument();
    expect(screen.queryByText("Nothing here")).not.toBeInTheDocument();
  });
});
