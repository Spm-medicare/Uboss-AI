"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";
import { controlClass } from "@/ui/field";
import {
  SheetCellBox,
  SheetRow,
  SheetTable,
  type SheetTone,
} from "@/ui/builder/sheet";

/**
 * The workbook's step table, and the same steps as cards on a narrow screen.
 *
 * ## Why both
 *
 * A table is the right instrument for the question people actually have — *which steps have no
 * approval, which one takes longest* — because a column answers it by being a column. Eight cards
 * make that eight separate places to look.
 *
 * And a table is the wrong instrument at 390 pixels. Sixteen columns there is not a table, it is
 * a horizontal scroll with one cell visible. So the same steps render as stacked cards below
 * `md`, with the column heads as field labels. **Not a different form** — the same values, the
 * same order, the same handlers. Only the arrangement changes, which is the one thing a screen
 * width should be allowed to change.
 *
 * ## The controls this does not have
 *
 * No drag-to-reorder. Moving a step is `move up` / `move down`, which works on a keyboard, works
 * on a touch screen, and cannot half-happen. A drag handle on a table row that scrolls sideways
 * is a way to drop a row somewhere nobody meant.
 */

/** One column of the sheet: its workbook label, the field it edits, and how wide it wants to be. */
export interface SheetColumn<Row> {
  /** The workbook's own head, verbatim — em dashes and all. */
  label: string;
  width?: "narrow" | "normal" | "wide";
  /** The editor for one cell. Given the row and a setter for it. */
  cell: (row: Row, set: (next: Row) => void, disabled: boolean) => ReactNode;
  /** The same value on the card layout. Defaults to `cell`. */
  card?: (row: Row, set: (next: Row) => void, disabled: boolean) => ReactNode;
}

export function SheetSteps<Row>({
  tone,
  columns,
  rows,
  disabled,
  onChange,
  blank,
  caption,
  addLabel,
  emptyLabel,
}: {
  tone: SheetTone;
  columns: readonly SheetColumn<Row>[];
  rows: readonly Row[];
  disabled: boolean;
  onChange: (next: Row[]) => void;
  /** A new, empty row. Given the position it will take, 1-based. */
  blank: (position: number) => Row;
  caption: string;
  addLabel: string;
  emptyLabel: string;
}) {
  const t = useTranslations("builder");

  const set = (index: number, next: Row) =>
    //  Editing the ghost row creates it. Anything else replaces the row in place.
    onChange(
      rows.length === 0 ? [next] : rows.map((row, at) => (at === index ? next : row)),
    );

  const add = () => onChange([...rows, blank(rows.length + 1)]);

  const remove = (index: number) => onChange(rows.filter((_, at) => at !== index));

  const move = (index: number, by: -1 | 1) => {
    const to = index + by;
    if (to < 0 || to >= rows.length) return;
    const next = [...rows];
    const [moved] = next.splice(index, 1);
    next.splice(to, 0, moved!);
    onChange(next);
  };

  //  **Step 1 is always on screen.**
  //
  //  An empty section used to be a sentence and an Add button, so the first thing anybody did on
  //  every form was press a button to make the thing they came to fill in appear. Now the table
  //  draws row 1 whether or not it exists yet — the same blank row a spreadsheet gives you.
  //
  //  Nothing is created until somebody types. `rows` is still empty in state and in the payload;
  //  the first edit to the ghost row is what calls `onChange` with a real row. A form that saved
  //  an empty step on load would put a step nobody wrote into the plan the analysis reads.
  const ghost = rows.length === 0 && !disabled;
  const shown: readonly Row[] = ghost ? [blank(1)] : rows;

  if (rows.length === 0 && disabled) {
    return (
      <div className="px-5 py-10 text-center">
        <p className="mx-auto max-w-md text-sm leading-relaxed text-muted-foreground">
          {emptyLabel}
        </p>
      </div>
    );
  }

  return (
    <>
      {/*  ── the sheet, on anything wide enough to be one ──────────────────── */}
      <div className="hidden md:block">
        <SheetTable
          tone={tone}
          caption={caption}
          columns={[t("stepColumn"), ...columns.map((column) => column.label), null]}
        >
          {shown.map((row, index) => (
            <SheetRow key={index} number={index + 1} tone={tone}>
              {columns.map((column) => (
                <SheetCellBox key={column.label} width={column.width ?? "normal"}>
                  {column.cell(row, (next) => set(index, next), disabled)}
                </SheetCellBox>
              ))}
              <SheetCellBox width="narrow">
                <RowControls
                  index={index}
                  total={shown.length}
                  disabled={disabled}
                  onMove={(by) => move(index, by)}
                  onRemove={() => remove(index)}
                />
              </SheetCellBox>
            </SheetRow>
          ))}
        </SheetTable>

        {!disabled ? (
          <div className="border-t border-border bg-muted/30 px-3 py-2.5">
            <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={add}>
              {addLabel}
            </Button>
          </div>
        ) : null}
      </div>

      {/*  ── the same steps, stacked, on a phone ───────────────────────────── */}
      <div className="space-y-3 p-4 md:hidden">
        <ol className="space-y-3">
          {shown.map((row, index) => (
            <li key={index} className="rounded-lg border border-border bg-card p-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  {t("stepNumber", { number: index + 1 })}
                </span>
                <RowControls
                  index={index}
                  total={shown.length}
                  disabled={disabled}
                  onMove={(by) => move(index, by)}
                  onRemove={() => remove(index)}
                />
              </div>
              <div className="space-y-3">
                {columns.map((column) => (
                  <div key={column.label}>
                    <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                      {column.label}
                    </p>
                    {(column.card ?? column.cell)(
                      row,
                      (next) => set(index, next),
                      disabled,
                    )}
                  </div>
                ))}
              </div>
            </li>
          ))}
        </ol>

        {!disabled ? (
          <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={add} block>
            {addLabel}
          </Button>
        ) : null}
      </div>
    </>
  );
}

function RowControls({
  index,
  total,
  disabled,
  onMove,
  onRemove,
}: {
  index: number;
  total: number;
  disabled: boolean;
  onMove: (by: -1 | 1) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("builder");
  if (disabled) return null;

  return (
    <div className="flex items-center gap-0.5">
      <IconButton
        label={t("moveUp", { step: index + 1 })}
        disabled={index === 0}
        onClick={() => onMove(-1)}
      >
        ↑
      </IconButton>
      <IconButton
        label={t("moveDown", { step: index + 1 })}
        disabled={index === total - 1}
        onClick={() => onMove(1)}
      >
        ↓
      </IconButton>
      <IconButton label={t("removeStep", { step: index + 1 })} onClick={onRemove} danger>
        <Trash2 aria-hidden className="size-3.5" />
      </IconButton>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled = false,
  danger = false,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        "grid size-7 shrink-0 place-items-center rounded-md text-sm text-muted-foreground",
        "transition-colors duration-150 motion-reduce:transition-none",
        "hover:bg-accent hover:text-foreground",
        danger && "hover:bg-danger-soft hover:text-danger",
        "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        "disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent",
      )}
    >
      {children}
    </button>
  );
}

/**
 * A cell's text input.
 *
 * Borderless inside the table, because a table already draws its own grid and a bordered input in
 * every cell is two grids fighting. The focus ring is what marks the active cell, and it is
 * inset so it is not clipped by the cell's own edge.
 */
export function CellInput({
  value,
  onChange,
  disabled,
  label,
  placeholder,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled: boolean;
  /** The column head plus the row number. Never rendered — the column head is the visible one. */
  label: string;
  placeholder?: string;
}) {
  return (
    <input
      type="text"
      value={value}
      aria-label={label}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      className={cn(cellClass)}
    />
  );
}

/**
 * How every cell in the sheet is drawn.
 *
 * A visible border, always. The first version drew cells borderless and only showed an outline on
 * focus, on the reasoning that the table already has a grid — but the result was a row of blank
 * space where somebody had to click to find out whether a cell was even editable. On a form
 * people fill in from a paper sheet, a box that looks like a box is the whole affordance.
 */
const cellClass = cn(
  controlClass,
  "h-9 px-2 py-1.5",
  "focus-visible:-outline-offset-1",
  //  A read-only cell keeps its text at full contrast: it is a value somebody has to read, not a
  //  control they are being told they cannot use.
  "disabled:opacity-100 disabled:bg-muted/50 disabled:text-foreground",
);

/**
 * A cell that suggests without constraining.
 *
 * The workbook's dropdowns are *lists on a sheet* — somebody typing a trigger nobody thought of
 * is doing the right thing, and a `<select>` would refuse them. A `datalist` offers the list and
 * accepts anything, which is what the paper form does.
 *
 * Distinct from `CellSelect`, which is for the one field that really is a closed set.
 */
export function CellSuggest({
  value,
  onChange,
  options,
  disabled,
  label,
}: {
  value: string;
  onChange: (next: string) => void;
  options: readonly string[];
  disabled: boolean;
  label: string;
}) {
  //  One list element per column, shared by every row: a datalist per cell would be twenty
  //  copies of the same options in the DOM on a twenty-step form.
  const listId = `suggest-${label.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase()}`;
  return (
    <>
      <input
        type="text"
        value={value}
        list={options.length > 0 ? listId : undefined}
        aria-label={label}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={cn(cellClass)}
      />
      {options.length > 0 ? (
        <datalist id={listId}>
          {options.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
      ) : null}
    </>
  );
}

/** A cell's dropdown. Same reasoning as `CellInput`. */
export function CellSelect({
  value,
  onChange,
  options,
  disabled,
  label,
  placeholder,
}: {
  value: string;
  onChange: (next: string) => void;
  options: readonly string[];
  disabled: boolean;
  label: string;
  placeholder: string;
}) {
  return (
    <select
      value={value}
      aria-label={label}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      className={cn(cellClass)}
    >
      <option value="">{placeholder}</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}
