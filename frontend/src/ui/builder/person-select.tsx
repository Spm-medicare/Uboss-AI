"use client";

import { useTranslations } from "next-intl";

import { Field } from "@/ui";

/**
 * Naming a person, from the people this workspace actually has.
 *
 * ## Why it moved here
 *
 * Two identical copies of this existed, one inside the Job Builder's page and one inside the
 * Objective Builder's, and the two forms that did not have a copy are the two that could not be
 * submitted at all. The Agent Builder offered a free-text box writing a *label* while `submit()`
 * demanded a membership id, and the Supervisor offered nothing while its `submit()` demanded the
 * same. Both refusals read *"Name an approver — a person, not a role"* about a screen that gave
 * you no way to name a person.
 *
 * ## Why an approver has to be a person
 *
 * A role name cannot approve anything. `can_approve` compares the named approver against the
 * signed-in membership, so a label can never satisfy it and the approval can never happen — which
 * is why `submit()` refuses one. The label is still worth recording where the workbook named a
 * role, and it stays; it is a note about who the approver is *for*, not the approver.
 *
 * The list is whoever the caller passes. That is deliberately not decided here: the Objective's
 * people list answers "who may own or approve", which excludes somebody who has been invited and
 * has not accepted — an approver has to be able to act.
 */
export function PersonSelect({
  label,
  hint,
  required = false,
  value,
  people,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  /** Passed to `Field`, which marks it with a word rather than a symbol. */
  required?: boolean;
  value: string | null;
  people: { membership_id: string; display_name: string; job_title?: string | null }[];
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations("builder");
  return (
    <Field label={label} required={required} {...(hint ? { hint } : {})}>
      {(field) => (
        <select
          {...field}
          value={value ?? ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value || null)}
          className="h-9 w-full rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {/*  Nobody, spelled out. An empty first option with no words reads as a list that
              failed to load rather than as a choice not yet made. */}
          <option value="">{t("choosePerson")}</option>
          {people.map((person) => (
            <option key={person.membership_id} value={person.membership_id}>
              {person.display_name}
              {person.job_title ? ` — ${person.job_title}` : ""}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}
