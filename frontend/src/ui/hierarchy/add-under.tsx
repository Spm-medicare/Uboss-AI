"use client";

import { useMutation } from "@tanstack/react-query";
import { Building2, Plus, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { OrgUnitRead, PositionRead, UnitType } from "@/lib/api/contract";
import { ApiError, NetworkError } from "@/lib/api/errors";
import { addReportingLine, createPosition, createUnit } from "@/lib/api/hierarchy";
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
 * ## Designation is a grade, and that is why it can be stored
 *
 * Executive, Manager and Employee set `level` — the organisation's own seniority number, which
 * `hierarchy/models.py` describes as *"seniority as the customer counts it… not a permission."*
 * It is a grade, so it stays true whether or not somebody currently has reports; an HR system
 * has Manager-grade people with no direct reports every day of the week.
 *
 * That is deliberately **not** the same claim as "people report to this seat". That one is
 * `reports_to_position_id`, it is what draws the tree, and it is asked for separately below.
 * Collapsing the two would mean a chart that either hides a real reporting line or invents one.
 */

/** The three bands, and the grade each one writes. Lower is more senior. */
const DESIGNATIONS = [
  { id: "executive", level: 1 },
  { id: "manager", level: 2 },
  { id: "employee", level: 3 },
] as const;

type Designation = (typeof DESIGNATIONS)[number]["id"];

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
  const [designation, setDesignation] = useState<Designation>("employee");
  const [managerId, setManagerId] = useState(reportsTo?.id ?? "");

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
      const seat = await withStepUp(() =>
        createPosition({
          org_unit_id: unit.id,
          title: title.trim(),
          level: DESIGNATIONS.find((band) => band.id === designation)!.level,
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
      return seat;
    },
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  //  Every seat in the company, grouped by its department: a team lead reporting to a VP in
  //  another box is ordinary, and a picker limited to one unit could not express it.
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
            {save.error instanceof ApiError ? save.error.message : t("addFailed")}
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

        <Field
          label={kind === "person" ? t("positionTitle") : t("departmentName")}
          htmlFor="add-title"
          hint={kind === "person" ? t("positionTitleHint") : undefined}
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
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium">{t("designation")}</legend>
              <div className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-muted p-1">
                {DESIGNATIONS.map((band) => (
                  <button
                    key={band.id}
                    type="button"
                    aria-pressed={designation === band.id}
                    disabled={save.isPending}
                    onClick={() => setDesignation(band.id)}
                    className={cn(
                      "rounded-md px-2 py-2 text-sm font-medium",
                      "transition-colors duration-150 motion-reduce:transition-none",
                      "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                      designation === band.id
                        ? "bg-card text-foreground shadow-sm ring-1 ring-inset ring-border"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {t(`designations.${band.id}`)}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-xs text-muted-foreground">{t("designationHint")}</p>
            </fieldset>

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
