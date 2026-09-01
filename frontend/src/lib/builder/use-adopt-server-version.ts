"use client";

/**
 * Keeps a builder's form following the server, and gives a version conflict a way out.
 *
 * ## The bug this exists for
 *
 * Every Builder seeds its form once from the query and then advances it only on a successful save.
 * Plenty of other things advance the row: an analysis bumps an Objective's version twice, granting
 * a handler bumps a Supervisor's, and submitting, withdrawing and publishing bump all four. None of
 * those go through the save path, so the form kept the version it was mounted with — and that
 * version is used for two things:
 *
 * * **The idempotency key.** A second *Analyse* built the same key as the first, the server matched
 *   the fingerprint, and the stored response came back: the previous plan, presented as a fresh one.
 * * **`expected_version`.** The next save was judged against a version already spent, the server
 *   correctly refused it, and the screen said *"Somebody else saved this"* about nobody. `conflicted`
 *   then latched with nothing able to clear it, so autosave stopped for the rest of the session and
 *   the work lived in `pending` behind a browser unload prompt.
 *
 * ## What it does
 *
 * When the server's copy moves ahead of what this client last confirmed, the form takes it — but
 * only while nothing is queued. Every one of those out-of-band bumps comes from a button, so in
 * practice there is nothing to lose; and replacing the form while somebody is mid-sentence is the
 * data loss PLAN §6 forbids.
 *
 * When something *is* queued and the versions have genuinely diverged, that is a real conflict and
 * the screen says so. `resolveConflict` is what its recovery calls: take the server's version, keep
 * what was typed, and send it. §6's rule makes the option that keeps the text the one to offer, and
 * the copy beside it says plainly that it writes over what the other person changed in those
 * fields.
 *
 * ## Why it is a hook and not four copies
 *
 * Because four copies is how the drift it fixes happened. `unsavedSince` existed twice and was
 * missing from the screen that lost the most data; `is_editable` disagreed across four modules for
 * the same reason. One effect, one place.
 */

import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import type { Autosave } from "@/lib/builder/use-autosave";

export function useAdoptServerVersion<T extends { version: number }>({
  server,
  confirmedVersionRef,
  setDraft,
  autosave: { pendingDraft, schedule, clearConflict },
  reload,
}: {
  /** The row as the query currently has it. */
  server: T;
  /** The newest version this client has been given — the ref the save path reads. */
  confirmedVersionRef: MutableRefObject<number>;
  setDraft: Dispatch<SetStateAction<T>>;
  autosave: Pick<Autosave<T>, "pendingDraft" | "schedule" | "clearConflict">;
  /** Ask the query to refetch. The effect below reacts when the fresher row arrives. */
  reload: () => void;
}): { resolveConflict: () => void } {
  //  Set by `resolveConflict`, read once by the effect. A ref rather than state because it must
  //  be visible to the effect that the very next render runs, without causing that render.
  const resolvingRef = useRef(false);

  useEffect(() => {
    /*  **Ahead, not merely different.**

        The query's cached row is routinely *behind* what this client has confirmed: a save returns
        the new version immediately and the refetch that follows it lands a moment later, so for
        that moment the cache still holds the previous one. Comparing for inequality adopted it —
        rolling the form back a version and resetting the confirmed version with it, which made the
        very next save stale and produced the 409 this hook exists to prevent. Found by walking the
        four Builders in a browser: the first edit saved, the second was refused every time. */
    if (server.version <= confirmedVersionRef.current) return;

    const queued = pendingDraft();
    if (queued !== null && !resolvingRef.current) return;

    confirmedVersionRef.current = server.version;

    //  Nothing queued, or nothing to resolve: the server's copy is simply the truth.
    if (!resolvingRef.current || queued === null) {
      resolvingRef.current = false;
      setDraft(server);
      return;
    }

    /*  Resolving a conflict: send what was refused, against the version that refused it.

        Deliberately not a field-level merge. From here the only two rows available are the refused
        draft and the server's new one, and a difference between them could be either a keystroke or
        the other person's edit — the hook cannot tell which, and guessing would silently discard
        one of them. So the refused payload goes out whole, which is exactly what the original save
        was going to write, and the alert says plainly that it replaces the other version. That is
        the promise the button makes, kept literally.

        Computed here rather than inside a `setDraft` updater, because scheduling a save is a side
        effect and React is allowed to call an updater twice. */
    resolvingRef.current = false;
    const merged = { ...queued, version: server.version };
    setDraft(merged);
    //  Queued straight away: the person pressed a button meaning "send my change", and waiting for
    //  another keystroke would leave it sitting unsent behind an alert that has just closed.
    schedule(merged);
    //  Depends on the three stable callbacks rather than on the autosave object, whose identity
    //  changes every render — otherwise this effect re-runs on every keystroke for nothing.
  }, [server, confirmedVersionRef, setDraft, pendingDraft, schedule]);

  const resolveConflict = useCallback(() => {
    resolvingRef.current = true;
    //  Cleared first, so the effect above is allowed to schedule again the moment the fresher row
    //  arrives — `schedule` is a no-op while the conflict stands.
    clearConflict();
    reload();
  }, [clearConflict, reload]);

  return { resolveConflict };
}
