"use client";

/**
 * Autosave, and the four states PLAN §6 asks it to show.
 *
 * The rule the whole hook exists for is §6's: *"Never lose entered data after an error."* Three
 * things follow from it, and each one is a way a form loses somebody's afternoon:
 *
 * **A failed save never clears what is pending.** The typed value stays in the form and stays
 * queued, so the next attempt sends it. A hook that dropped it on failure would be a hook that
 * silently discards work the moment a connection blips.
 *
 * **A version conflict stops autosaving.** Retrying a save the server already refused would
 * either fail forever or, worse, succeed against a version somebody else wrote — overwriting
 * their edit. The person is told, and they decide.
 *
 * **Offline is not failure.** The browser says whether it has a connection; that is a different
 * state with a different message and a different recovery, and the save resumes on reconnect
 * rather than being re-attempted every two seconds against a network that is not there.
 *
 * ## Why saving is a loop rather than a call
 *
 * It used to be a single call guarded by an `inFlight` flag, and an edit made while a save was
 * out was dropped on the floor: `run` returned early, nothing rescheduled it, and the request
 * that was already going out finished by setting the state to **saved** — so the badge read
 * *"Saved at 14:32"* over a change that had never been sent, and stayed that way until the next
 * keystroke happened to queue another timer. Pressing **Save draft** in that window did the same
 * thing and resolved as though it had worked.
 *
 * So `run` now drains: while something is pending, it sends it. One request at a time, and the
 * badge cannot say *saved* while `pending` still holds something. A failure leaves the loop with
 * the draft still pending, which is the rule above.
 *
 * ## Why the conflict can be cleared
 *
 * `conflicted` latched and there was no way to unlatch it — the flag was returned read-only and
 * nothing reset it — so one 409 stopped autosaving for the rest of the session, with the work held
 * only in `pending` behind a `beforeunload` prompt. And the conflict was usually not a conflict:
 * a version bump from the same person's own analysis or handler grant, which the form had no way
 * to notice. That cause is fixed where it belongs, in the screens; this hook now also lets the
 * screen say the conflict is resolved, because sometimes it genuinely is.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, NetworkError } from "@/lib/api/errors";
import type { SaveState } from "@/ui/builder/builder-layout";

/** Long enough not to save mid-word, short enough that a distracted person loses nothing. */
const QUIET_MS = 1200;

export interface Autosave<T> {
  state: SaveState;
  /** Queue a save. Called on every edit; the debounce decides when it actually goes. */
  schedule: (draft: T) => void;
  /** Save now — the explicit Save Draft button. Resolves when the save settles. */
  saveNow: (draft: T) => Promise<void>;
  /** True while a version conflict is unresolved. Autosave is paused until it is cleared. */
  conflicted: boolean;
  /**
   * The edit that has been queued and not yet accepted by the server, or null.
   *
   * Two callers need it. A screen checks for null before adopting a fresher copy of the row —
   * replacing the form while somebody is mid-sentence would discard what they had typed. And the
   * recovery from a version conflict needs the draft the server *refused*, which is exactly this
   * one; reading the component's current state instead would be a guess at the same thing.
   */
  pendingDraft: () => T | null;
  /**
   * Resume autosaving after a conflict the screen has resolved — by reloading the row, or by
   * deciding to write over what changed. Whatever is still pending goes out on the next edit or
   * the next Save draft.
   */
  clearConflict: () => void;
}

export function useAutosave<T>(
  save: (draft: T) => Promise<void>,
  options: { enabled?: boolean } = {},
): Autosave<T> {
  const enabled = options.enabled ?? true;
  const [state, setState] = useState<SaveState>({ kind: "clean" });
  const [conflicted, setConflicted] = useState(false);

  //  Held in refs rather than state: a timer firing must read the latest draft, and re-rendering
  //  on every keystroke to keep state in sync would make typing the expensive operation.
  const pending = useRef<T | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  //  The draining loop, while one is running. Doubles as the re-entry guard and as the thing
  //  `saveNow` waits on, so an explicit save that arrives mid-flight resolves when its own edit
  //  has actually been sent rather than when somebody else's finished.
  const running = useRef<Promise<void> | null>(null);
  const saveRef = useRef(save);
  //  Kept current in an effect rather than assigned during render: writing a ref while
  //  rendering is what React's rules forbid, and under Strict Mode the write happens twice.
  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  const drain = useCallback(async () => {
    //  One at a time, and keep going while anything is queued — including an edit that arrived
    //  while the previous request was out.
    while (pending.current !== null) {
      const draft = pending.current;
      setState({ kind: "saving" });
      try {
        await saveRef.current(draft);
      } catch (error) {
        if (error instanceof NetworkError) {
          setState({ kind: "offline" });
        } else if (error instanceof ApiError && error.status === 409) {
          //  Somebody else saved. Retrying would overwrite them — and this is not rare on a form
          //  that autosaves: a second tab produces it within seconds.
          setConflicted(true);
          setState({ kind: "failed", message: error.message });
        } else {
          setState({
            kind: "failed",
            message: error instanceof Error ? error.message : String(error),
          });
        }
        //  `pending` deliberately keeps the draft, and the loop stops. The next edit, the next
        //  Save draft, or coming back online sends it.
        return;
      }

      //  Cleared only on success, and only if nothing newer arrived while the request was out —
      //  in which case the loop goes round again rather than reporting a save that is behind.
      if (pending.current === draft) {
        pending.current = null;
        setState({ kind: "saved", at: new Date() });
      }
    }
  }, []);

  const run = useCallback((): Promise<void> => {
    if (running.current) return running.current;
    const loop = drain().finally(() => {
      running.current = null;
    });
    running.current = loop;
    return loop;
  }, [drain]);

  const schedule = useCallback(
    (draft: T) => {
      if (!enabled || conflicted) return;
      pending.current = draft;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void run(), QUIET_MS);
    },
    [enabled, conflicted, run],
  );

  const saveNow = useCallback(
    async (draft: T) => {
      if (timer.current) clearTimeout(timer.current);
      pending.current = draft;
      //  Waits for the loop, not merely for whatever request happens to be in the air. If a save
      //  was already going out, this draft is the next thing the loop sends, and the promise
      //  resolves once it has — so a button that says it saved has.
      await run();
    },
    [run],
  );

  const pendingDraft = useCallback(() => pending.current, []);

  const clearConflict = useCallback(() => {
    setConflicted(false);
    setState((current) => (current.kind === "failed" ? { kind: "clean" } : current));
  }, []);

  //  Coming back online retries what is still queued. Nothing is lost by being offline; it is
  //  only delayed, which is what the badge says.
  useEffect(() => {
    function onOnline() {
      if (pending.current !== null && !conflicted) void run();
    }
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [run, conflicted]);

  //  A last chance to say something before the tab closes with an unsaved edit. The browser
  //  shows its own wording; all this does is ask for the prompt.
  useEffect(() => {
    function onLeave(event: BeforeUnloadEvent) {
      if (pending.current !== null) event.preventDefault();
    }
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, []);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  return { state, schedule, saveNow, conflicted, pendingDraft, clearConflict };
}
