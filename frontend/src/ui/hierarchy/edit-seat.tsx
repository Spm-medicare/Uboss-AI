"use client";

import { useMutation } from "@tanstack/react-query";
import { MoveRight, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import type { OrgUnitRead, PositionRead } from "@/lib/api/contract";
import { ApiError, NetworkError } from "@/lib/api/errors";
import {
  addReportingLine,
  archivePosition,
  archiveUnit,
  moveUnit,
  updatePosition,
  updateUnit,
} from "@/lib/api/hierarchy";
import { useStepUp } from "@/ui/auth/step-up";
import { gradesInUse } from "@/ui/hierarchy/add-under";
import { Alert, Button, Dialog, Field, Input } from "@/ui";

/**
 * Changing a seat, or taking it out of the chart.
 *
 * ## Archived, not deleted — and the word on the button says so
 *
 * `archivePosition` sets `archived_at`; the row stays. That is the product's design and it is the
 * right one: a structure's history is evidence, and "who reported to whom last March" is a
 * question an auditor asks. A button labelled *Delete* over an operation that archives would be
 * a control that does not do what it says, so this one says **Remove** and the confirmation
 * spells out what actually happens — the seat leaves the chart, and the record of it does not.
 *
 * ## The confirmation is a sentence, not a checkbox
 *
 * It names the seat and says what will happen to the person in it. "Are you sure?" tells nobody
 * anything, and the one thing worth confirming here is the consequence somebody has not thought
 * of: removing an occupied seat leaves that person unplaced.
 */

const DESIGNATIONS = [
  { id: "executive", level: 1 },
  { id: "manager", level: 2 },
  { id: "employee", level: 3 },
] as const;

/**
 * The words for a seat recorded before `designation` existed.
 *
 * Empty for a level the product never labelled, so opening such a seat shows an empty field
 * rather than a grade nobody chose.
 */
function spelledBand(level: number | null | undefined): string {
  if (level === 1) return "Executive";
  if (level === 2) return "Manager";
  if (level === 3) return "Employee";
  return "";
}

export function EditSeatDialog({
  position,
  units,
  onClose,
  onDone,
}: {
  position: PositionRead;
  units: OrgUnitRead[];
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const tCommon = useTranslations("common");
  const withStepUp = useStepUp();

  const [title, setTitle] = useState(position.title);
  //  The same suggestions the Add form offers — this organisation's grades first, then the three
  //  the product can order. Imported rather than re-derived: two forms writing one column must
  //  not offer two vocabularies.
  const gradeOptions = gradesInUse(units);

  //  The stored words, or the old band's for a seat recorded before the field existed — so
  //  opening an older seat does not silently blank its grade.
  const [designation, setDesignation] = useState<string>(
    position.designation ?? spelledBand(position.level),
  );
  const [managerId, setManagerId] = useState(position.reports_to_position_id ?? "");
  //  Which box the seat sits in. A seat in the wrong department was previously unfixable: the
  //  only way to correct it was to remove the seat and make another one, which throws away the
  //  record of who held the first — and that record is the evidence the whole module exists to
  //  keep. The backend has always accepted `org_unit_id` here; nothing offered it.
  const [unitId, setUnitId] = useState(position.org_unit_id);
  const [confirming, setConfirming] = useState(false);
  //  Generated rather than written down: a hard-coded `htmlFor` is a duplicate id the moment two
  //  of these are mounted, and a duplicate id points a label at the wrong control.
  const unitFieldId = useId();

  //  Only live departments. An archived one is not on the chart, and the server refuses a seat
  //  moved into one — offering it would mean explaining a refusal afterwards.
  const departments = units.filter((candidate) => candidate.archived_at === null);
  const movingSeat = unitId !== position.org_unit_id;

  const save = useMutation({
    mutationFn: async () => {
      const band = DESIGNATIONS.find(
        (entry) => entry.id === designation.trim().toLowerCase(),
      );
      await withStepUp(() =>
        updatePosition(position.id, {
          title: title.trim(),
          designation: designation.trim() || null,
          //  The rank of a known band, or null. A grade this product cannot order is stored
          //  faithfully and sorts last; inventing a number would be inventing a rank.
          level: band ? band.level : null,
          //  Only when it changed. Sending the department it is already in would write
          //  "Moved position …" into the history for a move nobody made.
          ...(movingSeat ? { org_unit_id: unitId } : {}),
          expected_version: position.version,
        }),
      );
      //  Only when it changed. Re-drawing a line that is already there would be a second edge
      //  with the same meaning, and the history would record a change nobody made.
      if (managerId && managerId !== (position.reports_to_position_id ?? "")) {
        await withStepUp(() =>
          addReportingLine(position.id, {
            manager_position_id: managerId,
            effective_from: new Date().toISOString().slice(0, 10),
            kind: "primary",
          }),
        );
      }
    },
    onSuccess: () => {
      onDone();
      onClose();
    },
    //  Two writes, and the first may have committed before the second failed. Refreshing on the
    //  way out of the failure means the chart shows what actually happened rather than the state
    //  before the click, and the dialog picks up the seat's new version from live data — so the
    //  retry carries the version the row now holds instead of a spent one.
    onError: () => onDone(),
  });

  const remove = useMutation({
    mutationFn: () => withStepUp(() => archivePosition(position.id, position.version)),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  const candidates = units
    .map((unit) => ({
      unit,
      //  Never itself: a seat that reports to itself is a cycle, and the server refuses it. Not
      //  offering it is better than offering it and explaining the refusal afterwards.
      positions: (unit.positions ?? []).filter(
        (candidate) => candidate.archived_at === null && candidate.id !== position.id,
      ),
    }))
    .filter((group) => group.positions.length > 0);

  const error = save.error ?? remove.error;
  const busy = save.isPending || remove.isPending;

  return (
    <Dialog
      title={t("editSeatTitle")}
      description={position.holder ? t("editSeatHeld", { name: position.holder.display_name }) : t("editSeatVacant")}
      busy={busy}
      onClose={onClose}
      icon={
        <span
          aria-hidden
          className="grid size-10 place-items-center rounded-lg bg-primary/10 text-primary"
        >
          <Pencil className="size-5" />
        </span>
      }
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!title.trim() || busy) return;
          save.mutate();
        }}
      >
        {error ? (
          <Alert tone={error instanceof NetworkError ? "offline" : "danger"}>
            {error instanceof ApiError ? error.message : t("addFailed")}
          </Alert>
        ) : null}

        <Field label={t("positionTitle")} htmlFor="edit-title" required>
          {(field) => (
            <Input
              {...field}
              value={title}
              autoFocus
              disabled={busy}
              onChange={(event) => setTitle(event.target.value)}
            />
          )}
        </Field>

        <Field label={t("designation")} hint={t("designationHint")}>
          {(field) => (
            <>
              <Input
                {...field}
                list="edit-designation-options"
                value={designation}
                disabled={busy}
                placeholder={t("designationPlaceholder")}
                onChange={(event) => setDesignation(event.target.value)}
              />
              {/*  The same suggestions the Add form offers — this organisation's own grades,
                  then the three the product knows how to order. Two forms writing one column
                  must not offer two vocabularies. */}
              <datalist id="edit-designation-options">
                {gradeOptions.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            </>
          )}
        </Field>

        {/*  Before "reports to", because that list is grouped by department and reads better once
            this one is settled. Deliberately not a drag on the chart: a drag has no undo prompt,
            no confirmation and no keyboard, and re-parenting a seat is not a gesture worth
            getting wrong by a few pixels. */}
        <Field
          label={t("seatDepartment")}
          htmlFor={unitFieldId}
          hint={movingSeat ? t("seatDepartmentMoving") : t("seatDepartmentHint")}
        >
          {(field) => (
            <select
              {...field}
              value={unitId}
              disabled={busy}
              onChange={(event) => setUnitId(event.target.value)}
              className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field label={t("reportsTo")} htmlFor="edit-reports-to" required={false}>
          {(field) => (
            <select
              {...field}
              value={managerId}
              disabled={busy}
              onChange={(event) => setManagerId(event.target.value)}
              className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="">{t("reportsToNobody")}</option>
              {candidates.map((group) => (
                <optgroup key={group.unit.id} label={group.unit.name}>
                  {group.positions.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.holder
                        ? `${candidate.holder.display_name} · ${candidate.title}`
                        : `${candidate.title} · ${t("vacant")}`}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
        </Field>

        {/*  Separated from the form's own actions by a rule. A destructive control beside Save is
            one mis-click from a change nobody meant. */}
        <div className="space-y-3 border-t border-border pt-4">
          {confirming ? (
            <Alert tone="danger" title={t("removeSeatConfirmTitle", { title: position.title })}>
              <p>
                {position.holder
                  ? t("removeSeatHeld", { name: position.holder.display_name })
                  : t("removeSeatVacant")}
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  type="button"
                  variant="danger"
                  size="sm"
                  busy={remove.isPending}
                  onClick={() => remove.mutate()}
                >
                  {t("removeSeatConfirm")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => setConfirming(false)}
                >
                  {tCommon("cancel")}
                </Button>
              </div>
            </Alert>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              icon={<Trash2 className="size-3.5" />}
              className="px-0 text-danger hover:bg-transparent hover:underline"
              onClick={() => setConfirming(true)}
            >
              {t("removeSeat")}
            </Button>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>
              {tCommon("cancel")}
            </Button>
            <Button
              type="submit"
              variant="primary"
              busy={save.isPending}
              disabled={!title.trim() || remove.isPending}
            >
              {tCommon("save")}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

/**
 * Renaming a department, or taking it out of the chart.
 *
 * Same shape as the seat dialog and the same honesty about the verb: the server archives, so the
 * button says Remove. It also says what happens to what is inside — a department with seats in it
 * is not an empty box, and somebody about to remove one should be told that before they do.
 */
export function EditUnitDialog({
  unit,
  units,
  onClose,
  onDone,
}: {
  unit: OrgUnitRead;
  /** Every department, so a new parent can be offered and its own subtree ruled out. */
  units: OrgUnitRead[];
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const tCommon = useTranslations("common");
  const withStepUp = useStepUp();

  const [name, setName] = useState(unit.name);
  const [confirming, setConfirming] = useState(false);
  const [parentId, setParentId] = useState(unit.parent_id ?? "");
  const [confirmingMove, setConfirmingMove] = useState(false);
  const parentFieldId = useId();
  /*  Focus follows the confirmation.

      The button that opens it is the button that unmounts, so focus fell to `<body>` — and the
      panel wraps Tab by listening for keys inside itself, which means the keyboard was left
      outside a modal with no way back in. Moving focus to the confirming action also puts the
      sentence explaining what is about to happen in a screen reader's path before the control
      that does it. */
  const confirmMoveRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirmingMove) confirmMoveRef.current?.focus();
  }, [confirmingMove]);
  const seats = (unit.positions ?? []).filter((p) => p.archived_at === null).length;

  /*  Everything under this department, however deep.
      Needed twice: to say what a move takes with it, and to keep those same departments out of
      the list of places it can go. The database refuses a cycle — migration 0011 walks
      `parent_id` upward and raises — so offering one would only mean explaining a refusal after
      somebody chose it. */
  const subtree = useMemo(() => {
    const children = new Map<string, OrgUnitRead[]>();
    for (const candidate of units) {
      const key = candidate.parent_id ?? "";
      children.set(key, [...(children.get(key) ?? []), candidate]);
    }
    const found: OrgUnitRead[] = [];
    const queue = [unit.id];
    while (queue.length > 0) {
      //  `shift` on a queue this size is fine, and a visited set is unnecessary: `parent_id` is
      //  acyclic by database constraint, so this terminates.
      const next = queue.shift() as string;
      for (const child of children.get(next) ?? []) {
        found.push(child);
        queue.push(child.id);
      }
    }
    return found;
  }, [units, unit.id]);

  const live = subtree.filter((candidate) => candidate.archived_at === null);
  const travellingSeats = live.reduce(
    (total, candidate) =>
      total + (candidate.positions ?? []).filter((p) => p.archived_at === null).length,
    seats,
  );

  const excluded = new Set([unit.id, ...subtree.map((candidate) => candidate.id)]);
  const parentOptions = units.filter(
    (candidate) => candidate.archived_at === null && !excluded.has(candidate.id),
  );
  const chosenParent = parentOptions.find((candidate) => candidate.id === parentId);
  const parentChanged = parentId !== (unit.parent_id ?? "") && chosenParent !== undefined;

  const save = useMutation({
    mutationFn: () =>
      withStepUp(() =>
        updateUnit(unit.id, { name: name.trim(), expected_version: unit.version }),
      ),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  /*  Its own action, not part of Save.

      Two reasons, and the second is a bug this shape cannot have. The first is that the backend
      keeps moving separate on purpose — `OrgUnitMove` says re-parenting "is a different kind of
      change from correcting a spelling, and it reads differently in the revision history because
      it is a different endpoint" — and a UI that folds them together contradicts the record it
      writes. The second: Save and Move are two requests against one row, and each one increments
      `version`. Chained, the second would carry the version the first had already spent and come
      back with *"changed by somebody else while you were editing"* — naming a conflict with
      nobody, caused by the click itself. Separate actions cannot reach that state. */
  const move = useMutation({
    mutationFn: () =>
      withStepUp(() =>
        moveUnit(unit.id, { new_parent_id: parentId, expected_version: unit.version }),
      ),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  const remove = useMutation({
    mutationFn: () => withStepUp(() => archiveUnit(unit.id, unit.version)),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  const error = save.error ?? move.error ?? remove.error;
  const busy = save.isPending || move.isPending || remove.isPending;

  return (
    <Dialog
      title={t("editUnitTitle")}
      description={t("editUnitBody")}
      busy={busy}
      onClose={onClose}
      icon={
        <span
          aria-hidden
          className="grid size-10 place-items-center rounded-lg bg-primary/10 text-primary"
        >
          <Pencil className="size-5" />
        </span>
      }
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim() || busy) return;
          save.mutate();
        }}
      >
        {error ? (
          <Alert tone={error instanceof NetworkError ? "offline" : "danger"}>
            {error instanceof ApiError ? error.message : t("addFailed")}
          </Alert>
        ) : null}

        <Field label={t("departmentName")} htmlFor="edit-unit-name" required>
          {(field) => (
            <Input
              {...field}
              value={name}
              autoFocus
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>

        {/*  Moving, in its own bordered section with its own button — because it is its own
            request, and because the thing worth confirming is not "are you sure" but *what comes
            with it*. A department is not the box; it is everything in the box.

            The whole section goes when there is nowhere to put it. That happens only at the top of
            the organisation, where everything else is beneath it and `new_parent_id` cannot be
            null — and the chart does not offer Edit on the company at all, so in practice this is
            a guard rather than a state anybody reaches. It was a paragraph explaining itself,
            which is worse than absent: copy nobody can see is copy nobody maintains. */}
        {parentOptions.length === 0 ? null : (
        <div className="space-y-3 border-t border-border pt-4">
          <p className="text-sm font-medium">{t("moveUnitSection")}</p>

          {confirmingMove && chosenParent ? (
            <Alert
              tone="warning"
              title={t("moveUnitConfirmTitle", { name: unit.name, parent: chosenParent.name })}
            >
              <p>
                {live.length === 0 && travellingSeats === 0
                  ? t("moveUnitImpactEmpty")
                  : t("moveUnitImpact", {
                      seats: travellingSeats,
                      departments: live.length,
                    })}
              </p>
              <div className="mt-3 flex gap-2">
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  ref={confirmMoveRef}
                  busy={move.isPending}
                  onClick={() => move.mutate()}
                >
                  {t("moveUnitConfirm")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => setConfirmingMove(false)}
                >
                  {tCommon("cancel")}
                </Button>
              </div>
            </Alert>
          ) : (
            <>
              <Field
                label={t("parentDepartment")}
                htmlFor={parentFieldId}
                hint={t("parentDepartmentHint")}
              >
                {(field) => (
                  <select
                    {...field}
                    value={parentId}
                    disabled={busy}
                    onChange={(event) => setParentId(event.target.value)}
                    className="h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {/*  The department it is already under, so the select opens showing the truth
                        rather than a change nobody asked for. Empty only while it is at the top,
                        which the branch above already handles. */}
                    {parentOptions.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={busy || !parentChanged}
                icon={<MoveRight className="size-3.5" />}
                onClick={() => setConfirmingMove(true)}
              >
                {t("moveUnitAction")}
              </Button>
            </>
          )}
        </div>
        )}

        <div className="space-y-3 border-t border-border pt-4">
          {confirming ? (
            <Alert tone="danger" title={t("removeUnitConfirmTitle", { name: unit.name })}>
              <p>{seats > 0 ? t("removeUnitWithSeats", { count: seats }) : t("removeUnitEmpty")}</p>
              <div className="mt-3 flex gap-2">
                <Button
                  type="button"
                  variant="danger"
                  size="sm"
                  busy={remove.isPending}
                  onClick={() => remove.mutate()}
                >
                  {t("removeUnitConfirm")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => setConfirming(false)}
                >
                  {tCommon("cancel")}
                </Button>
              </div>
            </Alert>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              icon={<Trash2 className="size-3.5" />}
              className="px-0 text-danger hover:bg-transparent hover:underline"
              onClick={() => setConfirming(true)}
            >
              {t("removeUnit")}
            </Button>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>
              {tCommon("cancel")}
            </Button>
            <Button
              type="submit"
              variant="primary"
              busy={save.isPending}
              disabled={!name.trim() || remove.isPending}
            >
              {tCommon("save")}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}
