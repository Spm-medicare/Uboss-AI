"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Building2, Plus, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { OrgUnitRead, PositionRead, UnitType } from "@/lib/api/contract";
import { NetworkError } from "@/lib/api/errors";
import {
  addReportingLine,
  createPosition,
  createUnit,
  fetchPlaceablePeople,
} from "@/lib/api/hierarchy";
import { cn } from "@/lib/cn";
import { useStepUp } from "@/ui/auth/step-up";
import { Alert, Button, Dialog, Field, Input } from "@/ui";

/**
 * One `+`, and a choice of what goes under it.
 *
 * Every box and every seat on the chart has the same button, and it opens the same dialog. The
 * alternative — two buttons per box for department and position, and a third on each seat — is
 * five controls on a card the size of a business card, and somebody having to know which one they
 * want before they have decided.
 *
 * **It opens as a modal, not in place.** The forms used to expand inside the box they belonged
 * to, which widened the box, moved every connector line and reflowed the chart around the thing
 * being typed into. A form that rearranges the diagram it is about cannot be used.
 *
 ## Designation is a grade, in the organisation's own words
 *
 * It is a **text field**, not three buttons. Executive / Manager / Employee is a reasonable
 * default set and is not what companies call their grades: *Senior Manager*, *AVP*, *Associate
 * Director*, *Consultant*, *Registrar*. Being made to pick one of three makes the chart describe
 * a company that does not exist.
 *
 * The `datalist` is built from what this organisation already uses, plus those three — so the
 * second *Senior Manager* is one keystroke instead of a fresh spelling, and the vocabulary is
 * the customer's rather than ours.
 *
 * It is a grade, so it stays true whether or not somebody currently has reports; an HR system
 * has Manager-grade people with no direct reports every day of the week. `level` — the number
 * that *orders* seats, which `hierarchy/models.py` calls *"seniority as the customer counts
 * it… not a permission"* — is still written, from the three known bands when the text matches
 * one, and left null otherwise. Text cannot be ordered; that is why both exist.
 *
 * That is deliberately **not** the same claim as "people report to this seat". That one is
 * `reports_to_position_id`, it is what draws the tree, and it is asked for separately below.
 * Collapsing the two would mean a chart that either hides a real reporting line or invents one.
 */


export function AddUnderDialog({
  unit,
  units,
  reportsTo,
  onClose,
  onDone,
}: {
  /** The department this is being added to. */
  unit: OrgUnitRead;
  /** Every unit, so a manager anywhere in the company can be chosen. */
  units: OrgUnitRead[];
  /** The seat the `+` was pressed on, if it was pressed on one. Pre-selects the manager. */
  reportsTo?: PositionRead | undefined;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const tCommon = useTranslations("common");
  const withStepUp = useStepUp();

  const [kind, setKind] = useState<"person" | "department">("person");
  const [title, setTitle] = useState("");

  //  **The department's most senior seat, when no seat was pressed.**
  //
  //  This used to default to `""` — *"Nobody — top of the organisation"* — which is the one
  //  answer that is almost never right: it makes a second root, and the new person appears at
  //  the top of the chart rather than under the department they were added to. That was reported
  //  as "it goes somewhere else", and it was this.
  //
  //  Most senior means lowest `level`, because 1 is the most senior. Still overridable, and
  //  "Nobody" is still in the list — a chief executive has to be expressible.
  const [managerId, setManagerId] = useState(
    () => reportsTo?.id ?? seniorSeatIn(unit) ?? "",
  );

  //  The person's name as typed. Empty is a real answer — a vacant seat is how an organisation
  //  draws a shape before it hires into it, and §5 requires vacancies to be visible.
  const [personName, setPersonName] = useState("");
  //  Only needed for a name the workspace does not have. Held here rather than in a second
  //  dialog: adding a colleague is one action, and splitting it in two would make somebody
  //  finish a form to be shown another.
  const [personEmail, setPersonEmail] = useState("");

  //  The workspace's people. Only fetched while the dialog is open, and only for a person: adding
  //  a department has no use for it.
  //  `hierarchy/people`, not `objectives/people`: this asks who *works here*, which includes
  //  colleagues who have been invited and not yet signed in. The narrower list offered two of
  //  the twenty-seven people already visible on the chart.
  const people = useQuery({
    queryKey: ["hierarchy", "people"],
    queryFn: ({ signal }) => fetchPlaceablePeople(signal),
    enabled: kind === "person",
  });

  const save = useMutation({
    mutationFn: async () => {
      if (kind === "department") {
        return withStepUp(() =>
          createUnit({
            name: title.trim(),
            unit_type: "department" as UnitType,
            parent_id: unit.id,
          }),
        );
      }

      //  The seat first, then the line to its manager. If the second fails, a seat exists with
      //  no manager — visible, editable and obviously incomplete. The error is shown rather than
      //  swallowed, so nobody is told the reporting line was drawn when it was not.
      //  **Resolved before anything is created.** A name nobody in the workspace answers to
      //  cannot become a person — `memberships.user_id` is NOT NULL, so there is no row to point
      //  at — and creating the seat anyway would leave somebody looking at a vacant box they
      //  believe they filled. So it is refused here, with the reason, and nothing is written.
      const named = personName.trim();
      //  If the list never loaded, the reason a name does not match is *that* — not the name.
      //  Saying "nobody is called that" when the request failed sends somebody off to check a
      //  spelling that was never the problem.
      if (named && people.error) {
        throw new Error(t("peopleUnavailable"));
      }
      const match = named
        ? (people.data ?? []).find(
            (person) =>
              person.display_name.trim().toLowerCase() === named.toLowerCase(),
          )
        : undefined;

      //  A name nobody answers to becomes a colleague, if an address was given. Created first:
      //  everything after this can be retried against a person who exists, and the other order
      //  leaves a seat waiting for somebody who was never made.
      let holderId = match?.membership_id;
      if (named && !match) {
        const address = personEmail.trim();
        if (!address) throw new Error(t("needEmailFor", { name: named }));
        const { invitePerson } = await import("@/lib/api/hierarchy");
        const added = await withStepUp(() =>
          invitePerson({ display_name: named, email: address }),
        );
        holderId = added.membership_id;
      }

      const seat = await withStepUp(() =>
        createPosition({
          org_unit_id: unit.id,
          title: title.trim(),
        }),
      );
      if (managerId) {
        await withStepUp(() =>
          addReportingLine(seat.id, {
            manager_position_id: managerId,
            effective_from: new Date().toISOString().slice(0, 10),
            kind: "primary",
          }),
        );
      }
      //  The person last, and only if one was named. Same ordering as the manager line and the
      //  same reason: a failure here leaves a vacant seat somebody can see and fill, not a
      //  person attached to nothing.
      //  The person last, and only if one was named. Same ordering as the manager line and the
      //  same reason: a failure here leaves a vacant seat somebody can see and fill, not a
      //  person attached to nothing.
      if (holderId) {
        const { assignPerson } = await import("@/lib/api/hierarchy");
        await withStepUp(() =>
          assignPerson(seat.id, {
            membership_id: holderId,
            effective_from: new Date().toISOString().slice(0, 10),
          }),
        );
      }
      return seat;
    },
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  //  Every seat in the company, grouped by its department: a team lead reporting to a VP in
  //  another box is ordinary, and a picker limited to one unit could not express it.
  //  A name that has been typed and matches nobody. Computed on every render rather than on
  //  submit, so the address field appears while somebody is still typing rather than after they
  //  have been refused.
  const typed = personName.trim();
  const isNewName =
    typed.length > 0 &&
    !(people.data ?? []).some(
      (person) =>
        person.display_name.trim().toLowerCase() === typed.toLowerCase(),
    );

  const groups = units
    .map((candidate) => ({
      unit: candidate,
      positions: (candidate.positions ?? []).filter((p) => p.archived_at === null),
    }))
    .filter((group) => group.positions.length > 0);

  return (
    <Dialog
      title={
        reportsTo
          ? t("addUnderSeat", { title: reportsTo.title })
          : t("addUnderUnit", { unit: unit.name })
      }
      description={t("addUnderBody")}
      busy={save.isPending}
      onClose={onClose}
      icon={
        <span
          aria-hidden
          className="grid size-10 place-items-center rounded-lg bg-primary/10 text-primary"
        >
          {kind === "person" ? (
            <UserPlus className="size-5" />
          ) : (
            <Building2 className="size-5" />
          )}
        </span>
      }
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!title.trim() || save.isPending) return;
          save.mutate();
        }}
      >
        {save.error ? (
          <Alert tone={save.error instanceof NetworkError ? "offline" : "danger"}>
            {/*  **Any message the code wrote gets shown.** This used to read
                `error instanceof ApiError ? error.message : t("addFailed")`, so every failure the
                *form itself* raised — "nobody called X is in this workspace" — was replaced by
                "That could not be added", and the one sentence that said what to do about it was
                thrown away. The generic line is now only for an error carrying nothing to say. */}
            {save.error.message?.trim() ? save.error.message : t("addFailed")}
          </Alert>
        ) : null}

        {/*  What is being added, first — everything below it depends on the answer. */}
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">{t("whatToAdd")}</legend>
          <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-muted p-1">
            {(["person", "department"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={kind === option}
                disabled={save.isPending}
                onClick={() => setKind(option)}
                className={cn(
                  "rounded-md px-3 py-2 text-sm font-medium",
                  "transition-colors duration-150 motion-reduce:transition-none",
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                  kind === option
                    ? "bg-card text-foreground shadow-sm ring-1 ring-inset ring-border"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t(`addKind.${option}`)}
              </button>
            ))}
          </div>
        </fieldset>

        {kind === "person" ? (
          <Field label={t("employeeName")} hint={t("employeeNameHint")}>
            {(field) => (
              <>
                <Input
                  {...field}
                  list="people-options"
                  value={personName}
                  disabled={save.isPending}
                  placeholder={t("employeeNamePlaceholder")}
                  onChange={(event) => setPersonName(event.target.value)}
                />
                {/*  Suggestions, not a gate: you type, and the workspace's people appear. The
                    list is `hierarchy/people`, so invited colleagues are in it — they are most
                    of an organisation during onboarding. */}
                <datalist id="people-options">
                  {(people.data ?? []).map((person) => (
                    <option key={person.membership_id} value={person.display_name} />
                  ))}
                </datalist>
              </>
            )}
          </Field>
        ) : null}

        {/*  Appears only for a name the workspace does not have. Somebody picking a colleague
            from the suggestions never sees it; somebody typing a new person is asked the one
            thing that cannot be inferred — an account is reached by email. */}
        {kind === "person" && isNewName ? (
          <Field label={t("newPersonEmail")} hint={t("newPersonEmailHint")}>
            {(field) => (
              <Input
                {...field}
                type="email"
                value={personEmail}
                disabled={save.isPending}
                placeholder="dibyanshu@company.com"
                onChange={(event) => setPersonEmail(event.target.value)}
              />
            )}
          </Field>
        ) : null}

        <Field
          label={kind === "person" ? t("positionTitle") : t("departmentName")}
          htmlFor="add-title"
          hint={
            kind === "person" ? t("positionTitleHint") : t("departmentNameHint")
          }
          required
        >
          {(field) => (
            <Input
              {...field}
              value={title}
              autoFocus
              disabled={save.isPending}
              placeholder={
                kind === "person"
                  ? t("positionTitlePlaceholder")
                  : t("departmentNamePlaceholder")
              }
              onChange={(event) => setTitle(event.target.value)}
            />
          )}
        </Field>

        {kind === "person" ? (
          <>
            <Field
              label={t("reportsTo")}
              htmlFor="reports-to"
              hint={t("reportsToHint")}
              required={false}
            >
              {(field) => (
                <select
                  {...field}
                  value={managerId}
                  disabled={save.isPending}
                  onChange={(event) => setManagerId(event.target.value)}
                  className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {/*  "Nobody" is a real answer, not a blank: somebody has to be at the top, and
                      a picker that forces a manager cannot describe a chief executive. */}
                  <option value="">{t("reportsToNobody")}</option>
                  {groups.map((group) => (
                    <optgroup key={group.unit.id} label={group.unit.name}>
                      {group.positions.map((position) => (
                        <option key={position.id} value={position.id}>
                          {position.holder
                            ? `${position.holder.display_name} · ${position.title}`
                            : `${position.title} · ${t("vacant")}`}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              )}
            </Field>
          </>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" disabled={save.isPending} onClick={onClose}>
            {tCommon("cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            busy={save.isPending}
            disabled={!title.trim()}
            icon={save.isPending ? undefined : <Plus className="size-3.5" />}
          >
            {save.isPending ? t("adding") : t("add")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/**
 * The most senior live seat in a department, or `null` if it has none.
 *
 * Lowest `level` wins, because 1 is the most senior; a seat with no level is treated as the least
 * senior rather than the most, so an unlabelled seat cannot outrank a director. Ties break on the
 * title so the answer is stable between renders — an arbitrary-but-stable choice is better than
 * one that changes each time the dialog opens.
 */
function seniorSeatIn(unit: OrgUnitRead): string | null {
  const live = (unit.positions ?? []).filter((p) => p.archived_at === null);
  if (live.length === 0) return null;
  const sorted = [...live].sort((a, b) => {
    const left = a.level ?? Number.MAX_SAFE_INTEGER;
    const right = b.level ?? Number.MAX_SAFE_INTEGER;
    return left === right ? a.title.localeCompare(b.title) : left - right;
  });
  return sorted[0]!.id;
}


/**
 * Every designation already in use, commonest first, followed by the three known bands.
 *
 * Built from the tree rather than from a fixed list, so the suggestions are the customer's
 * vocabulary. Case-insensitive dedupe keeps the spelling somebody actually used rather than a
 * normalised one nobody typed.
 */
export function gradesInUse(units: OrgUnitRead[]): string[] {
  const counts = new Map<string, { label: string; n: number }>();
  for (const unit of units) {
    for (const position of unit.positions ?? []) {
      const value = (position.designation ?? "").trim();
      if (!value) continue;
      const key = value.toLowerCase();
      const seen = counts.get(key);
      if (seen) seen.n += 1;
      else counts.set(key, { label: value, n: 1 });
    }
  }
  const used = [...counts.values()]
    .sort((a, b) => b.n - a.n || a.label.localeCompare(b.label))
    .map((entry) => entry.label);

  const defaults = ["Executive", "Manager", "Employee"].filter(
    (band) => !counts.has(band.toLowerCase()),
  );
  return [...used, ...defaults];
}
