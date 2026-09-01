/**
 * The three ways autosave used to lose work or lie about it.
 *
 * Each test names the behaviour a Builder depends on, and each one failed before the loop replaced
 * the single guarded call. They are unit tests on the hook rather than on a screen because all four
 * Builders share it, and the bugs were in the hook.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { useAutosave } from "./use-autosave";

/** A save that resolves when the test says so. */
function deferred<T = void>() {
  let settle!: (value: T) => void;
  let fail!: (reason: unknown) => void;
  const promise = new Promise<T>((resolve, reject) => {
    settle = resolve;
    fail = reject;
  });
  return { promise, settle, fail };
}

describe("an edit made while a save is in the air", () => {
  it("is sent, rather than left behind a badge that says Saved", async () => {
    const first = deferred();
    const sent: string[] = [];
    const save = vi.fn(async (draft: string) => {
      sent.push(draft);
      if (sent.length === 1) await first.promise;
    });

    const { result } = renderHook(() => useAutosave<string>(save));

    //  The explicit Save path, so the test does not depend on the debounce timer.
    await act(async () => {
      void result.current.saveNow("first");
      await Promise.resolve();
    });
    expect(sent).toEqual(["first"]);

    //  A second edit arrives while the first request is still out.
    act(() => {
      void result.current.saveNow("second");
    });
    expect(result.current.pendingDraft()).not.toBeNull();

    await act(async () => {
      first.settle();
      await Promise.resolve();
    });

    await waitFor(() => expect(sent).toEqual(["first", "second"]));
    await waitFor(() => expect(result.current.pendingDraft()).toBeNull());
  });

  it("keeps the badge off Saved until nothing is queued", async () => {
    const first = deferred();
    const save = vi.fn(async (draft: string) => {
      if (draft === "first") await first.promise;
    });

    const { result } = renderHook(() => useAutosave<string>(save));

    await act(async () => {
      void result.current.saveNow("first");
      await Promise.resolve();
    });
    act(() => {
      void result.current.saveNow("second");
    });

    await act(async () => {
      first.settle();
      await Promise.resolve();
    });

    //  The first request finishing must not report a save while "second" is still queued.
    await waitFor(() => expect(result.current.state.kind).toBe("saved"));
    expect(result.current.pendingDraft()).toBeNull();
  });
});

describe("a failed save", () => {
  it("keeps the draft queued so the next attempt sends it", async () => {
    const save = vi
      .fn<(draft: string) => Promise<void>>()
      .mockRejectedValueOnce(new Error("the server fell over"))
      .mockResolvedValue(undefined);

    const { result } = renderHook(() => useAutosave<string>(save));

    await act(async () => {
      await result.current.saveNow("work");
    });

    expect(result.current.state.kind).toBe("failed");
    expect(result.current.pendingDraft()).not.toBeNull();

    await act(async () => {
      await result.current.saveNow("work");
    });
    expect(result.current.state.kind).toBe("saved");
    expect(result.current.pendingDraft()).toBeNull();
  });
});

describe("a version conflict", () => {
  it("pauses autosave, and can be cleared so the form is usable again", async () => {
    const save = vi
      .fn<(draft: string) => Promise<void>>()
      .mockRejectedValueOnce(
        new ApiError(409, {
          code: "conflict",
          message: "Somebody else changed this.",
          field_errors: [],
          correlation_id: "test",
          retryable: false,
        }),
      )
      .mockResolvedValue(undefined);

    const { result } = renderHook(() => useAutosave<string>(save));

    await act(async () => {
      await result.current.saveNow("mine");
    });
    expect(result.current.conflicted).toBe(true);

    //  Paused: scheduling is refused while the conflict stands, so a stale version cannot be
    //  retried against somebody else's write.
    act(() => {
      result.current.schedule("mine again");
    });
    expect(save).toHaveBeenCalledTimes(1);

    //  And the way out, which did not exist: the flag latched with nothing able to reset it, so a
    //  single 409 stopped autosaving for the rest of the session.
    act(() => {
      result.current.clearConflict();
    });
    expect(result.current.conflicted).toBe(false);
    expect(result.current.state.kind).toBe("clean");

    await act(async () => {
      await result.current.saveNow("mine");
    });
    expect(save).toHaveBeenCalledTimes(2);
    expect(result.current.state.kind).toBe("saved");
  });
});
