"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * The approved workbook, as screens.
 *
 * All four Builders are sheets in `UBOSS_Agent_Builder_Forms.xlsx`, and the client asked for the
 * sheets themselves: a coloured title bar, a heading block of label-and-value pairs, the
 * instruction line, then a **table with one row per step and one column per field**.
 *
 * ## Why a table and not a card per step
 *
 * The first version drew each step as its own card with the fields grouped inside. It reads well
 * for one step and badly for eight, because the question somebody actually has is *comparative* —
 * "which steps have no approval?", "which one takes longest?" — and comparing a field across
 * eight cards means eight separate places to look. A column answers it by being a column. The
 * workbook is a table for the same reason, and the client recognises it as their sheet.
 *
 * ## The first column is sticky, and that is the whole trick
 *
 * Form 3 has sixteen columns. It will scroll sideways on any laptop, exactly as the workbook does
 * in Excel. What makes that usable rather than infuriating is the step number staying put: you
 * always know which row you are reading. Without it, sideways scrolling on a wide table is how
 * people put data in the wrong row.
 *
 * Below `md` the table is replaced by the caller's own stacked layout — sixteen columns in 390
 * pixels is not a table anybody can read, and a card genuinely is better there.
 *
 * ## Column labels come from the workbook, verbatim
 *
 * Including the em dashes: `WHO — Person Name`, not `Who: Person name`. They were read out of the
 * `.xlsx` rather than copied from the previous build, because a copy of a copy is where a wrong
 * label survives. The heads are the client's own words and are the thing they check first.
 */

/** Which sheet this is. The client says "the blue one", so the hue is part of the vocabulary. */
export type SheetTone = "form-1" | "form-2" | "form-3" | "form-4";

const FILL: Record<SheetTone, string> = {
  "form-1": "var(--ub-form-1)",
  "form-2": "var(--ub-form-2)",
  "form-3": "var(--ub-form-3)",
  "form-4": "var(--ub-form-4)",
};

const WASH: Record<SheetTone, string> = {
  "form-1": "var(--ub-form-1-soft)",
  "form-2": "var(--ub-form-2-soft)",
  "form-3": "var(--ub-form-3-soft)",
  "form-4": "var(--ub-form-4-soft)",
};

/**
 * The sheet's own title bar.
 *
 * `title` is the workbook's `A1` — *"FORM 4 — AGENT BUILDER | DESIGN, CONTROLS & TESTS"* — and
 * `subtitle` is the instruction under it. Both verbatim, because somebody holding the printed
 * sheet is checking they are on the right one.
 */
export function SheetTitle({
  tone,
  title,
  subtitle,
  action,
}: {
  tone: SheetTone;
  title: string;
  subtitle?: string;
  /** A control that belongs to the whole sheet — the output toggle, usually. */
  action?: ReactNode;
}) {
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-t-xl px-4 py-3 text-white"
      style={{ backgroundColor: FILL[tone] }}
    >
      <div className="min-w-0">
        <h2 className="text-[0.8125rem] font-bold uppercase tracking-[0.06em]">{title}</h2>
        {subtitle ? (
          <p className="mt-1 max-w-prose text-xs leading-relaxed text-white/80">{subtitle}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/**
 * The heading block — the workbook's rows 4 to 7, label above value.
 *
 * Three to a row on a wide screen, one on a phone. The workbook puts them across the top and
 * that is where somebody looks for "who is the owner", so they stay above the table rather than
 * becoming a section of their own.
 */
export function SheetHead({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-x-5 gap-y-4 border-b border-border px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
      {children}
    </div>
  );
}

export function SheetCell({
  label,
  required = false,
  hint,
  wide = false,
  children,
}: {
  label: string;
  /** The workbook's asterisk. Rendered as a word, not a glyph — see `Field`. */
  required?: boolean;
  hint?: string;
  /** Spans the full row. For the one or two fields that are a sentence rather than a value. */
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={cn("min-w-0", wide && "sm:col-span-2 lg:col-span-3")}>
      <p className="mb-1.5 text-[0.6875rem] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
        {label}
        {required ? null : (
          <span className="ml-1.5 font-medium normal-case tracking-normal opacity-70">
            optional
          </span>
        )}
      </p>
      {children}
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * A value the screen worked out rather than one somebody typed.
 *
 * The workbook has you type totals. A typed total that disagrees with the rows below it is worse
 * than no total, so these are computed and marked as computed — otherwise it looks like a field
 * somebody forgot to fill in.
 */
export function SheetComputed({ children }: { children: ReactNode }) {
  return (
    <p className="flex h-10 items-center rounded-md border border-dashed border-border bg-muted px-3 text-sm font-semibold tabular-nums">
      {children}
    </p>
  );
}

/** The workbook's instruction line. */
export function SheetNote({ children }: { children: ReactNode }) {
  return (
    <p
      className="border-b px-4 py-2.5 text-xs leading-relaxed"
      style={{
        backgroundColor: "var(--ub-sheet-note)",
        borderColor: "var(--ub-sheet-note-line)",
        color: "var(--ub-sheet-note-ink)",
      }}
    >
      {children}
    </p>
  );
}

/**
 * A section bar inside a sheet — Form 4's `A. AGENT DESIGN CONFIRMATION`.
 *
 * The letter is set apart because that is how people refer to these out loud: "put it in section
 * B". It is also an `h3`, so the document outline matches what the sheet looks like.
 */
export function SheetSection({
  tone,
  letter,
  children,
  action,
}: {
  tone: SheetTone;
  /** `A`, `B`, `C`. Absent on a sheet with only one section. */
  letter?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-y px-4 py-2"
      style={{
        backgroundColor: WASH[tone],
        borderColor: `color-mix(in oklab, ${FILL[tone]} 28%, transparent)`,
      }}
    >
      <h3
        className="flex items-baseline gap-2 text-xs font-bold uppercase tracking-[0.07em]"
        style={{ color: `color-mix(in oklab, ${FILL[tone]} 78%, var(--ub-text))` }}
      >
        {letter ? (
          <span
            className="grid size-5 shrink-0 place-items-center rounded text-[0.6875rem] text-white"
            style={{ backgroundColor: FILL[tone] }}
          >
            {letter}
          </span>
        ) : null}
        {children}
      </h3>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/**
 * The table, in its own horizontal scroller.
 *
 * `overflow-x-auto` here rather than on the page: the sheet scrolls, the page does not. A wide
 * table that made the whole document scroll sideways would take the section rail and the header
 * with it.
 *
 * The first column is sticky. See the module docstring — it is what makes sixteen columns
 * survivable.
 */
export function SheetTable({
  tone,
  columns,
  children,
  caption,
}: {
  tone: SheetTone;
  /** The workbook's own heads, verbatim. `null` for a column of row controls. */
  columns: readonly (string | null)[];
  children: ReactNode;
  /** Read by a screen reader before the table. Says what one row is. */
  caption: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-max min-w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th
                key={column ?? `controls-${index}`}
                scope="col"
                className={cn(
                  "whitespace-nowrap border-b border-r border-border px-3 py-2 text-left align-bottom",
                  "text-[0.6875rem] font-bold uppercase tracking-[0.05em]",
                  "last:border-r-0",
                  //  The step number travels with the row. Without it, reading column fourteen of
                  //  row six means counting rows from the top after every scroll.
                  index === 0 && "sticky left-0 z-10",
                )}
                style={{
                  backgroundColor: WASH[tone],
                  color: `color-mix(in oklab, ${FILL[tone]} 72%, var(--ub-text))`,
                }}
              >
                {column ?? <span className="sr-only">Row actions</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/**
 * One row of the table.
 *
 * The number cell is drawn here rather than by the caller, so the sticky column and its
 * background can never be forgotten on one table and not another.
 */
export function SheetRow({
  number,
  children,
  tone,
}: {
  number: number | string;
  children: ReactNode;
  tone: SheetTone;
}) {
  return (
    <tr className="group/row">
      <th
        scope="row"
        className={cn(
          "sticky left-0 z-10 w-12 border-b border-r border-border bg-card px-3 py-1.5",
          "text-left align-top text-xs font-semibold tabular-nums text-muted-foreground",
          "group-hover/row:bg-accent",
        )}
        style={{ borderRightColor: `color-mix(in oklab, ${FILL[tone]} 28%, transparent)` }}
      >
        <span className="flex h-9 items-center">{number}</span>
      </th>
      {children}
    </tr>
  );
}

/**
 * One cell.
 *
 * `min-w` rather than a fixed width: a column of dropdowns does not need the width a column of
 * sentences does, and a table where every column is the widest column is a table nobody can see
 * two of at once.
 */
export function SheetCellBox({
  children,
  width = "normal",
}: {
  children: ReactNode;
  width?: "narrow" | "normal" | "wide";
}) {
  const widths = {
    narrow: "min-w-[7.5rem]",
    normal: "min-w-[11rem]",
    wide: "min-w-[15rem]",
  };
  return (
    <td
      className={cn(
        "border-b border-r border-border p-1.5 align-top last:border-r-0 group-hover/row:bg-accent/40",
        widths[width],
      )}
    >
      {children}
    </td>
  );
}

/** The sheet itself — the frame the pieces above sit in. */
export function Sheet({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {children}
    </div>
  );
}
