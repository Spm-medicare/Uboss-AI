"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A modal, for the times a form must not be part of the page behind it.
 *
 * The org chart is why this exists. Every "add a department" form opened *inside* the box it
 * belonged to, which pushed the box wider, moved every connector line, and reflowed the chart
 * around the thing somebody was trying to type into. A form that rearranges the diagram it is
 * about is a form that cannot be used.
 *
 * ## What it actually has to do
 *
 * **Escape closes it, and so does the backdrop.** Both are what people try first, and a modal
 * that ignores them is one somebody feels trapped in.
 *
 * **Focus goes in and comes back.** The first focusable control is focused on open, and whatever
 * was focused before is restored on close — otherwise a keyboard user lands back at the top of
 * the document each time, which on this screen means scrolling past the whole chart again.
 *
 * **Focus stays inside while it is open.** Tab from the last control wraps to the first. Without
 * it, tabbing walks off into the page behind, where a screen reader will happily read a form the
 * person cannot see.
 *
 * **The page behind does not scroll.** A modal over a scrolling page is the one interaction that
 * makes an interface feel broken on a phone.
 *
 * `aria-modal` and a labelled heading; the close button has a real accessible name rather than
 * a bare glyph.
 */
export function Dialog({
  title,
  description,
  icon,
  onClose,
  children,
  busy = false,
}: {
  title: string;
  description?: string;
  /** A mark beside the title. Decorative — the title says what this is. */
  icon?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /**
   * While a request is in flight. Escape and the backdrop stop closing, because closing would
   * leave a submitted change with nothing on screen reporting how it went.
   */
  busy?: boolean;
}) {
  const t = useTranslations("common");
  const panel = useRef<HTMLDivElement>(null);
  const returnFocusTo = useRef<HTMLElement | null>(null);

  //  Held in a ref so the document listener below always sees the current value without being
  //  torn down and re-added on every render. Synced in an effect rather than during render: a
  //  ref written while rendering is a side effect in a place React is allowed to run twice.
  const state = useRef({ onClose, busy });
  useEffect(() => {
    state.current = { onClose, busy };
  }, [onClose, busy]);

  useEffect(() => {
    returnFocusTo.current = document.activeElement as HTMLElement | null;

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";

    //  On the document rather than as a JSX handler on the backdrop. Escape has to work wherever
    //  focus is — including on a `<select>` that has swallowed the key — and a keydown handler on
    //  a plain `<div>` is a static element pretending to be interactive, which is both a lint
    //  error and a genuine accessibility fault.
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !state.current.busy) state.current.onClose();
    }
    document.addEventListener("keydown", onKeyDown);

    //  The first control, not the panel: opening a form and landing on its first field is the
    //  whole point of it being a form.
    const first = panel.current?.querySelector<HTMLElement>(
      'input, select, textarea, button, [href], [tabindex]:not([tabindex="-1"])',
    );
    first?.focus();

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = overflow;
      returnFocusTo.current?.focus();
    };
  }, []);

  /** Tab wrapping. On the panel, which is a real `role="dialog"` and may carry a key handler. */
  function trap(event: React.KeyboardEvent) {
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      panel.current?.querySelectorAll<HTMLElement>(
        'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    if (focusable.length === 0) return;

    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    //  Only the two ends need handling; everything between is the browser's own order, which is
    //  correct and should not be re-implemented.
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto p-4">
      {/*  The backdrop is a button, so clicking it to dismiss is a real control with a real name
          rather than a click handler bolted to a decorative `<div>`. Behind the panel, and out of
          the tab order — the close button in the corner is the one to reach by keyboard, and two
          stops that do the same thing is one too many. */}
      <button
        type="button"
        tabIndex={-1}
        aria-label={t("close")}
        disabled={busy}
        onClick={onClose}
        className="fixed inset-0 -z-10 cursor-default bg-black/40 backdrop-blur-[2px]"
      />

      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        onKeyDown={trap}
        className={cn(
          "w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-dialog",
        )}
      >
        <div className="flex items-start gap-3.5">
          {icon ? <span className="shrink-0">{icon}</span> : null}
          <div className="min-w-0 flex-1">
            <h2 id="dialog-title" className="text-base font-semibold">
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t("close")}
            className={cn(
              "-mr-1.5 -mt-1.5 grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground",
              "transition-colors duration-150 hover:bg-accent hover:text-foreground motion-reduce:transition-none",
              "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            <X aria-hidden className="size-4" />
          </button>
        </div>

        <div className="mt-5">{children}</div>
      </div>
    </div>
  );
}
