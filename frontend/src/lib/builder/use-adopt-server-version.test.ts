/**
 * The form follows the server — and knows when it must not.
 *
 * Before this hook, a Builder's form advanced only on a successful save, so every version bump
 * from somewhere else left it behind: an analysis (twice), a handler grant, a submit, a publish.
 * The stale version then went into the next idempotency key, replaying the previous analysis as
 * though it had just run, and into the next `expected_version`, earning a 409 that latched
 * `conflicted` for the rest of the session.
 *
 * The three cases below are the whole contract: take a fresher row, never take one over somebody's
 * typing, and give a real conflict a way out that keeps what was typed.
 */
import { act, renderHook } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { useAdoptServerVersion } from "./use-adopt-server-version";

interface Row {
  version: number;
  title: string;
  note: string;
}

/** Everything the hook needs, with the parts a test wants to watch. */
function harness(server: Row, options: { queued?: Row } = {}) {
  const confirmedVersionRef = createRef<number>() as { current: number };
  confirmedVersionRef.current = 1;

  const setDraft = vi.fn();
  const autosave = {
    pendingDraft: vi.fn(() => options.queued ?? null),
    schedule: vi.fn(),
    clearConflict: vi.fn(),
  };
  const reload = vi.fn();

  const { result, rerender } = renderHook(
    (next: Row) =>
      useAdoptServerVersion<Row>({
        server: next,
        confirmedVersionRef,
        setDraft,
        autosave,
        reload,
      }),
    { initialProps: server },
  );

  return { result, rerender, confirmedVersionRef, setDraft, autosave, reload };
}

const AT_ONE: Row = { version: 1, title: "Reduce quotation time", note: "" };
/** What somebody had typed when the save was refused. */
const TYPED: Row = { version: 1, title: "Reduce quotation time to one day", note: "" };
const AT_THREE: Row = { version: 3, title: "Reduce quotation time", note: "from the server" };

describe("when the server moves ahead", () => {
  it("takes the fresher row, so the next save is not judged against a spent version", () => {
    const { rerender, confirmedVersionRef, setDraft } = harness(AT_ONE);

    expect(setDraft).not.toHaveBeenCalled();
    expect(confirmedVersionRef.current).toBe(1);

    //  An analysis has run: two version bumps, and nothing went through the save path.
    act(() => rerender(AT_THREE));

    expect(confirmedVersionRef.current).toBe(3);
    expect(setDraft).toHaveBeenCalledWith(AT_THREE);
  });

  it("does nothing when the version has not changed", () => {
    const { rerender, setDraft } = harness(AT_ONE);
    //  A refetch that returns the same row is a new object; adopting on identity would replace the
    //  form on every background refresh.
    act(() => rerender({ ...AT_ONE }));
    expect(setDraft).not.toHaveBeenCalled();
  });

  it("never rolls back to a row the cache has not caught up on", () => {
    /*  The bug this file gained a test for after walking the four Builders in a browser: the first
        edit saved and the second was refused, every time.

        A save returns the new version straight away and the refetch that follows lands a moment
        later, so in between the query's cached row is *behind* what this client has confirmed.
        Adopting on inequality took that older row — rolling the form back a version and resetting
        the confirmed version with it — which made the next save stale and produced exactly the 409
        this hook exists to prevent. */
    const { rerender, confirmedVersionRef, setDraft } = harness(AT_ONE);
    confirmedVersionRef.current = 4; // a save has just returned v4

    act(() => rerender({ ...AT_ONE, version: 3 })); // the cache is still on v3

    expect(setDraft).not.toHaveBeenCalled();
    expect(confirmedVersionRef.current).toBe(4);
  });
});

describe("when somebody is typing", () => {
  it("leaves the form alone, because replacing it would discard the keystrokes", () => {
    const { rerender, confirmedVersionRef, setDraft } = harness(AT_ONE, { queued: TYPED });

    act(() => rerender(AT_THREE));

    expect(setDraft).not.toHaveBeenCalled();
    expect(confirmedVersionRef.current).toBe(1);
  });
});

describe("resolving a real conflict", () => {
  it("clears the flag, reloads, then keeps what was typed and sends it", () => {
    const { result, rerender, confirmedVersionRef, setDraft, autosave, reload } = harness(AT_ONE, {
      queued: TYPED,
    });

    act(() => result.current.resolveConflict());

    //  Cleared before the reload, so the effect is allowed to schedule when the fresher row lands.
    expect(autosave.clearConflict).toHaveBeenCalled();
    expect(reload).toHaveBeenCalled();

    act(() => rerender(AT_THREE));

    expect(confirmedVersionRef.current).toBe(3);
    expect(setDraft).toHaveBeenCalledTimes(1);

    //  The refused draft, at the version that refused it — not a field-level merge, because from
    //  here a difference between the two rows could be a keystroke or the other person's edit and
    //  nothing can tell them apart. Computed outside the state updater, so React calling that
    //  updater twice cannot send twice.
    const [merged] = setDraft.mock.calls[0] as [Row];

    expect(merged.version).toBe(3);
    expect(merged.title).toBe("Reduce quotation time to one day");
    expect(autosave.schedule).toHaveBeenCalledWith(merged);
  });

  it("only resolves once, so an ordinary later refresh does not re-send", () => {
    const { result, rerender, setDraft, autosave } = harness(AT_ONE, { queued: TYPED });

    act(() => result.current.resolveConflict());
    act(() => rerender(AT_THREE));
    expect(autosave.schedule).toHaveBeenCalledTimes(1);

    setDraft.mockClear();
    act(() => rerender({ ...AT_THREE, version: 4 }));

    //  Still pending, and no longer resolving: the form is left alone again.
    expect(setDraft).not.toHaveBeenCalled();
    expect(autosave.schedule).toHaveBeenCalledTimes(1);
  });
});
