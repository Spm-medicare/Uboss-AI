"use client";

import type { CurrentStepInput, JobStepInput } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import {
  CellInput,
  CellSelect,
  CellSuggest,
  type SheetColumn,
} from "@/ui/builder/design-table";

/**
 * The workbook's step columns, for Forms 2 and 3.
 *
 * **Every label here was read out of `UBOSS_Agent_Builder_Forms.xlsx` row 9**, not copied from the
 * previous build and not translated. They are the client's own headings on the sheet they print,
 * and matching them is the thing they check first — em dashes included. A copy of a copy is where
 * a wrong heading survives, so the source is the source.
 *
 *     Form 2 — Objective Builder | Existing Workflow   14 columns
 *     Form 3 — Job Builder | Exact Job Method          16 columns
 *
 * ## The two columns that are not on the sheet
 *
 * Form 3 carries `mode` (human, AI or hybrid) and `depends_on`. Neither is a workbook column;
 * both are PLAN §9's, and the work mode is the distinction the whole product is built around.
 * They are drawn **after** the sixteen rather than mixed in, so somebody comparing the screen to
 * their sheet reads sixteen columns in order and then two more that are plainly the product's.
 * Hiding them would lose real fields; interleaving them would make the sheet unrecognisable.
 */

/** A plain text cell for a string field on `Row`. */
function text<Row>(key: keyof Row, width?: "narrow" | "normal" | "wide"): SheetColumn<Row> {
  return {
    label: "",
    ...(width ? { width } : {}),
    cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
      return (
        <CellInput
          value={(row[key] as string | null | undefined) ?? ""}
          label={String(key)}
          disabled={disabled}
          onChange={(value) => set({ ...row, [key]: value || null })}
        />
      );
    },
  };
}

/** The same, with the workbook's label attached. */
function column<Row>(
  label: string,
  key: keyof Row,
  width?: "narrow" | "normal" | "wide",
): SheetColumn<Row> {
  return { ...text<Row>(key, width), label };
}

/**
 * Form 2's fourteen columns — `Form 2 - Objective`, row 9.
 *
 * `Current Problem` is tinted. It is the column the whole objective exists to fix, it is thirteen
 * along on a table that scrolls, and it is the one a reviewer is looking for.
 */
/**
 * The `Dropdown Lists` sheet, as the two forms use it.
 *
 * `problems` is Form 2's alone — Form 3 has no "current problem" column — so it is optional here
 * rather than duplicated into a second interface. An absent list means the cell simply suggests
 * nothing, which is the right behaviour for a column the sheet has no list for.
 */
export interface WorkbookLists {
  triggers: readonly string[];
  frequencies: readonly string[];
  work_places: readonly string[];
  problems?: readonly string[];
  approvals: readonly string[];
}

/** A cell offering the workbook's list and accepting anything else. */
function suggest<Row>(
  label: string,
  key: keyof Row,
  options: readonly string[],
  width?: "narrow" | "normal" | "wide",
): SheetColumn<Row> {
  return {
    label,
    ...(width ? { width } : {}),
    cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
      return (
        <CellSuggest
          value={(row[key] as string | null | undefined) ?? ""}
          options={options}
          label={label}
          disabled={disabled}
          onChange={(value) => set({ ...row, [key]: value || null })}
        />
      );
    },
  };
}

export function objectiveColumns<Row extends CurrentStepInput>(
  lists: WorkbookLists,
): readonly SheetColumn<Row>[] {
  return [
    column<Row>("WHO — Person Name", "who_person"),
    column<Row>("WHO — Role", "who_role"),
    suggest<Row>("WHEN — Trigger", "when_trigger", lists.triggers),
    suggest<Row>("WHEN — Frequency", "when_frequency", lists.frequencies, "narrow"),
    column<Row>("WHAT — Exact Work", "what_exact_work", "wide"),
    column<Row>("INPUT — What Is Used", "input_used"),
    column<Row>("INPUT — Received From", "input_received_from"),
    suggest<Row>("WHERE — Work Is Done", "where_done", lists.work_places),
    column<Row>("OUTPUT — What Is Produced", "output_produced"),
    column<Row>("OUTPUT — Sent To", "output_sent_to"),
    column<Row>("Time Taken", "time_taken", "narrow"),
    {
      label: "Current Problem",
      width: "wide",
      cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
        return (
          <div
            className={cn(
              "rounded-md",
              row.current_problem
                ? "bg-approval-soft ring-1 ring-inset ring-approval/30"
                : "",
            )}
          >
            <CellSuggest
              value={row.current_problem ?? ""}
              options={lists.problems ?? []}
              label="Current Problem"
              disabled={disabled}
              onChange={(value) => set({ ...row, current_problem: value || null })}
            />
          </div>
        );
      },
    },
    {
      label: "Approval",
      width: "narrow",
      cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
        return (
          <CellSuggest
            value={row.approval ?? ""}
            options={lists.approvals}
            label="Approval"
            disabled={disabled}
            onChange={(value) => set({ ...row, approval: value || null })}
          />
        );
      },
    },
  ];
}

/**
 * Form 3's sixteen columns — `Form 3 - Job Method`, row 9 — then §9's two.
 *
 * `If Missing / Wrong` is tinted for the same reason `Current Problem` is on Form 2: it is what
 * the step does when reality does not cooperate, and it is fifteen columns along.
 */
export function jobColumns<Row extends JobStepInput>(
  lists: WorkbookLists,
  modes: readonly string[],
  modeLabel: string,
): readonly SheetColumn<Row>[] {
  return [
    column<Row>("WHO — Person Name", "who_person"),
    column<Row>("WHO — Role", "who_role"),
    suggest<Row>("WHEN — Trigger", "when_trigger", lists.triggers),
    suggest<Row>("WHEN — Frequency", "when_frequency", lists.frequencies, "narrow"),
    column<Row>("WHAT — Exact Work", "what_exact_work", "wide"),
    column<Row>("INPUT — Exact Input", "input_exact"),
    column<Row>("WHERE — Input Is Found", "input_found_where"),
    column<Row>("HOW — Exact Method", "how_exact_method", "wide"),
    suggest<Row>("WHERE — Work Is Performed", "where_performed", lists.work_places),
    column<Row>("Rule / Formula / Check", "rule_formula_check", "wide"),
    column<Row>("Output", "output"),
    column<Row>("Output Destination", "output_destination"),
    {
      label: "Approval",
      width: "narrow",
      cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
        return (
          <CellSuggest
            value={row.approval ?? ""}
            options={lists.approvals}
            label="Approval"
            disabled={disabled}
            onChange={(value) => set({ ...row, approval: value || null })}
          />
        );
      },
    },
    {
      label: "If Missing / Wrong",
      width: "wide",
      cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
        return (
          <div
            className={cn(
              "rounded-md",
              row.if_missing_or_wrong
                ? "bg-approval-soft ring-1 ring-inset ring-approval/30"
                : "",
            )}
          >
            <CellInput
              value={row.if_missing_or_wrong ?? ""}
              label="If Missing / Wrong"
              disabled={disabled}
              onChange={(value) => set({ ...row, if_missing_or_wrong: value || null })}
            />
          </div>
        );
      },
    },
    column<Row>("Time", "time_taken", "narrow"),

    //  ── after the sheet: PLAN §9's own fields ────────────────────────────────
    {
      label: modeLabel,
      width: "narrow",
      cell: function Cell(row: Row, set: (next: Row) => void, disabled: boolean) {
        return (
          <CellSelect
            value={row.mode ?? ""}
            options={modes}
            label={modeLabel}
            placeholder="—"
            disabled={disabled}
            onChange={(value: string) =>
              set({ ...row, mode: (value || null) as JobStepInput["mode"] })
            }
          />
        );
      },
    },
  ];
}
