/**
 * What somebody typed while a save was in the air.
 *
 * A builder's save is debounced, so typing continues after the request goes out. When the server
 * answers, its copy is the one that carries the new version — and taking it wholesale would erase
 * every keystroke made in the meantime. So the server's row is the base, and this puts back the
 * fields that have moved on since the payload was sent.
 *
 * Two identical copies of this existed, one inside the Job Builder's page and one inside the
 * Objective Builder's, and the Supervisor — which had none — replaced its draft with the server's
 * copy outright and lost whatever had been typed. A third copy would have been the wrong answer to
 * that.
 *
 * `version`, `updated_at` and `is_editable` are the server's to state, never the form's, so they
 * are never carried back. Anything else a caller wants excluded it names.
 */
export function unsavedSince<T extends object>(
  /** The form as it stands now. */
  current: T,
  /** The form as it was when the payload was sent. */
  sent: T,
  /** Extra keys the server owns. Added to `version`, `updated_at` and `is_editable`. */
  serverOwned: readonly (keyof T)[] = [],
): Partial<T> {
  const owned = new Set<string | number | symbol>([
    "version",
    "updated_at",
    "is_editable",
    ...serverOwned,
  ]);

  const changed: Partial<T> = {};
  for (const key of Object.keys(current) as (keyof T)[]) {
    if (owned.has(key)) continue;
    //  Structural comparison, because a step table is an array of objects and a reference check
    //  would call every row changed on every render.
    if (JSON.stringify(current[key]) !== JSON.stringify(sent[key])) {
      changed[key] = current[key];
    }
  }
  return changed;
}
