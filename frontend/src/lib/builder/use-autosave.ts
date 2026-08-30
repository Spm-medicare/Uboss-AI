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
  /** True while a version conflict is unresolved. Autosave is paused until the form reloads. */
  conflicted: boolean;
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
  const inFlight = useRef(false);
  const saveRef = useRef(save);
  //  Kept current in an effect rather than assigned during render: writing a ref while
  //  rendering is what React's rules forbid, and under Strict Mode the write happens twice.
  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  const run = useCallback(async () => {
    if (inFlight.current || pending.current === null) return;

    const draft = pending.current;
    inFlight.current = true;
    setState({ kind: "saving" });

    try {
      await saveRef.current(draft);
      //  Cleared only on success, and only if nothing newer arrived while the request was out.
      if (pending.current === draft) pending.current = null;
      setState({ kind: "saved", at: new Date() });
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
      //  `pending` deliberately keeps the draft. The next edit or the next Save Draft sends it.
    } finally {
      inFlight.current = false;
    }
  }, []);

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
      await run();
    },
    [run],
  );

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

  return { state, schedule, saveNow, conflicted };
}
