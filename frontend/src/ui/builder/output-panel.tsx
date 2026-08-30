"use client";

import { PanelRight, PanelRightClose, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * What a run produced, beside the form rather than under it.
 *
 * The previous build put results in a second column that the form folded away for, and the client
 * asked for that back. They are right, and the reason is not aesthetic: a result you have to
 * scroll past eight sections of form to reach is a result you check once and then stop checking.
 * Beside the form, the thing you changed and the thing it produced are on screen together.
 *
 * ## It opens itself, and it closes on request
 *
 * Running is the moment somebody wants the output, so a run opens the panel. Nothing else does —
 * a panel that opened on load would take half the screen from somebody who came to edit. Closing
 * is always available and always manual: results are never dismissed for you, because a result
 * that vanished is one nobody can say they read.
 *
 * ## What does *not* live here
 *
 * **Publish gates stay in the form.** They are the reason the Publish button is disabled, and a
 * reason hidden behind a toggle is a person clicking a dead button and learning nothing. The rule
 * this codebase keeps is that a control says what it does; the corollary is that a control which
 * *cannot* act says why, in the place somebody is looking.
 *
 * So this panel is for what a run *produced* — sandbox results, a proposed plan, a summary — and
 * never for what a person still has to do.
 *
 * ## A drawer, not a second column
 *
 * The previous build split the screen in two and folded the form away to read a result. This
 * slides in from the right instead, over the form, and closes back to it. Two reasons: a result
 * is read in bursts and edited between them, so the form should still be *there* rather than
 * folded to a strip; and a drawer can be opened from anywhere in the page — the section that ran
 * the thing owns the state, rather than the page having to hoist it to a layout column.
 *
 * On a phone it comes up from the bottom, because a 26rem drawer on a 390px screen is the screen.
 */
export function OutputPanel({
  open,
  onClose,
  label,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  /** The small line above the title — "Output · Form 4 · Agent Builder". */
  label: string;
  title: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLElement>(null);
  const tCommon = useTranslations("common");
  const closeLabel = tCommon("close");

  //  Escape closes it, wherever focus is. Not a `keydown` on the panel: somebody reading a result
  //  has usually clicked back into the form, and the key should still work.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  //  Scrolled to the top each time it opens. A second run that left the panel where the first
  //  one ended shows the middle of a new result as though it were the start of it.
  useEffect(() => {
    if (open) panel.current?.scrollTo({ top: 0 });
  }, [open]);

  if (!open) return null;

  return (
    <>
      {/*  Under `xl` the panel covers the page, so the form behind it needs to stop being
          clickable. Above `xl` there is no scrim: both columns are live at once, which is the
          whole point of the layout. */}
      {/*  The form behind stays visible and stops being clickable. Visible because the result is
          about it, and the person reads one against the other. */}
      <button
        type="button"
        tabIndex={-1}
        aria-label={closeLabel}
        onClick={onClose}
        className="fixed inset-0 z-40 cursor-default bg-black/25 backdrop-blur-[1px]"
      />

      <aside
        ref={panel}
        aria-label={title}
        className={cn(
          "fixed z-50 overflow-y-auto border-panel-line bg-panel text-panel-foreground shadow-dialog",
          //  Bottom sheet on a phone, right-hand drawer from `sm` up.
          "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-2xl border-t",
          "sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[30rem] sm:rounded-none sm:rounded-l-2xl sm:border-l sm:border-t-0",
        )}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-panel-line bg-panel px-4 py-3">
          <div className="min-w-0">
            <p className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-panel-muted">
              {label}
            </p>
            <h2 className="mt-0.5 truncate text-base font-semibold">{title}</h2>
          </div>
          <CloseButton onClose={onClose} />
        </div>

        <div className="px-4 py-4">{children}</div>
      </aside>
    </>
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  const t = useTranslations("common");
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label={t("close")}
      className={cn(
        "-mr-1 -mt-1 grid size-8 shrink-0 place-items-center rounded-md text-panel-muted",
        "transition-colors duration-150 hover:bg-panel-raised hover:text-panel-foreground motion-reduce:transition-none",
        "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
      )}
    >
      <X aria-hidden className="size-4" />
    </button>
  );
}

/**
 * The control that opens and closes it, for the sheet's title bar.
 *
 * White on the coloured bar rather than a `Button` variant: every variant this codebase has is
 * drawn for a light surface, and a ghost button on a saturated fill either disappears or needs a
 * per-form restyle — which is four variants of one control.
 */
export function OutputToggle({
  open,
  onToggle,
  count,
}: {
  open: boolean;
  onToggle: () => void;
  /** How many results are waiting. Absent when there are none — see below. */
  count?: number;
}) {
  const t = useTranslations("builder");

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-white/25 bg-white/10 px-2.5 py-1.5",
        "text-xs font-semibold text-white",
        "transition-colors duration-150 hover:bg-white/20 motion-reduce:transition-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
      )}
    >
      {open ? (
        <PanelRightClose aria-hidden className="size-3.5" />
      ) : (
        <PanelRight aria-hidden className="size-3.5" />
      )}
      {open ? t("hideOutput") : t("showOutput")}
      {/*  Only when there is something to show. A "0" beside "Show output" is an invitation to
           press a button that opens an empty panel. */}
      {!open && count ? (
        <span className="rounded-full bg-white px-1.5 text-[0.625rem] font-bold tabular-nums text-[color:var(--ub-text)]">
          {count}
        </span>
      ) : null}
    </button>
  );
}

/** Nothing has been run yet. Said plainly, with what to do about it. */
export function OutputEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="grid justify-items-center gap-2 px-6 py-16 text-center">
      <p className="max-w-[26ch] text-sm leading-relaxed text-panel-muted">{children}</p>
    </div>
  );
}

/** One block of result, with a heading. Several of these stack in the panel. */
export function OutputBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="border-b border-panel-line pb-5 last:border-b-0 last:pb-0 [&+&]:pt-5">
      <h3 className="text-xs font-bold uppercase tracking-[0.07em] text-panel-muted">
        {title}
      </h3>
      <div className="mt-2.5">{children}</div>
    </section>
  );
}
