/**
 * Each workbook column offers the list the sheet says it takes.
 *
 * This exists because one of them did not, invisibly, for as long as the Job Builder has had a
 * step table. Form 2 and Form 3 both have a column headed *Approval*, and they mean different
 * things:
 *
 * - Form 2 asks **who** signs off — Team Lead, Department Head, Quality, Regulatory.
 * - Form 3 asks **when** the sign-off happens — Before this step, After this step, Always.
 *
 * The job table offered Form 2's list. Nothing objected: the step fields accept a company's own
 * words on purpose, so "Team Lead" was written into a column meaning *when*, and published into an
 * immutable `JobVersion` where it cannot be corrected. Two approved lists, one of them in the
 * wrong column, and no symptom anywhere.
 *
 * A type now makes the mistake a compile error, and this makes it a test failure — because a type
 * only catches the wiring, and someone can still wire `approval_timings` to the wrong column.
 */
import { describe, expect, it } from "vitest";

import { jobColumns, objectiveColumns } from "./workbook-columns";

/*  Deliberately disjoint values rather than the real vocabularies. If the two lists shared a word
    — both begin with "No approval" in the real workbook — a test could pass while reading the
    wrong one. Nothing here appears in more than one list, so a wrong binding cannot be mistaken
    for a right one. */
const LISTS = {
  triggers: ["TRIGGER"],
  frequencies: ["FREQUENCY"],
  work_places: ["WORKPLACE"],
  problems: ["PROBLEM"],
  approvals: ["WHO-APPROVES"],
  approval_timings: ["WHEN-APPROVED"],
  missing_actions: ["WHEN-MISSING"],
};

/** The options a column would hand to its cell, without rendering React. */
function optionsOf(
  columns: readonly { label: string; cell?: unknown }[],
  label: string,
): readonly string[] {
  const column = columns.find((candidate) => candidate.label === label);
  if (!column) throw new Error(`no column labelled ${label}`);
  //  Every option-bearing cell is built by the same two helpers, and both close over the array
  //  they were given. Rendering is unnecessary to know which array that is: call the cell with a
  //  bare row and read the `options` prop off the element it returns.
  const cell = column.cell as (
    row: Record<string, unknown>,
    set: (next: unknown) => void,
    disabled: boolean,
  ) => { props?: Record<string, unknown> };
  const element = cell({}, () => {}, false);
  const found = findOptions(element);
  if (!found) throw new Error(`column ${label} offers no list`);
  return found;
}

/** The `options` prop, however deeply the cell wraps its input. */
function findOptions(node: unknown): readonly string[] | null {
  if (!node || typeof node !== "object") return null;
  const props = (node as { props?: Record<string, unknown> }).props;
  if (!props) return null;
  if (Array.isArray(props.options)) return props.options as readonly string[];
  const children = props.children;
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findOptions(child);
      if (found) return found;
    }
    return null;
  }
  return findOptions(children);
}

describe("the Job step table", () => {
  const columns = jobColumns(LISTS, ["Human"], "Mode");

  it("offers Approval Timing in the Approval column, not who approves", () => {
    expect(optionsOf(columns, "Approval")).toEqual(["WHEN-APPROVED"]);
  });

  it("offers the Missing Action list where a step says what to do when an input is wrong", () => {
    expect(optionsOf(columns, "If Missing / Wrong")).toEqual(["WHEN-MISSING"]);
  });

  it("still takes the shared lists for the columns both forms have", () => {
    expect(optionsOf(columns, "WHEN — Trigger")).toEqual(["TRIGGER"]);
    expect(optionsOf(columns, "WHERE — Work Is Performed")).toEqual(["WORKPLACE"]);
  });
});

describe("the Objective activity table", () => {
  const columns = objectiveColumns(LISTS);

  it("offers who approves, which is what Form 2 asks", () => {
    expect(optionsOf(columns, "Approval")).toEqual(["WHO-APPROVES"]);
  });

  it("does not borrow the job form's timing list", () => {
    expect(optionsOf(columns, "Approval")).not.toContain("WHEN-APPROVED");
  });
});
