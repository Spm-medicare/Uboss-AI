"use client";

import { useMutation } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { OrgUnitRead, PositionRead } from "@/lib/api/contract";
import { ApiError, NetworkError } from "@/lib/api/errors";
import {
  addReportingLine,
  archivePosition,
  archiveUnit,
  updatePosition,
  updateUnit,
} from "@/lib/api/hierarchy";
import { cn } from "@/lib/cn";
import { useStepUp } from "@/ui/auth/step-up";
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

function bandOf(level: number | null | undefined): (typeof DESIGNATIONS)[number]["id"] | "" {
  return DESIGNATIONS.find((band) => band.level === level)?.id ?? "";
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
  const [designation, setDesignation] = useState<string>(bandOf(position.level));
  const [managerId, setManagerId] = useState(position.reports_to_position_id ?? "");
  const [confirming, setConfirming] = useState(false);

  const save = useMutation({
    mutationFn: async () => {
      const band = DESIGNATIONS.find((entry) => entry.id === designation);
      await withStepUp(() =>
        updatePosition(position.id, {
          title: title.trim(),
          level: band ? band.level : null,
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

        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">{t("designation")}</legend>
          <div className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-muted p-1">
            {DESIGNATIONS.map((band) => (
              <button
                key={band.id}
                type="button"
                aria-pressed={designation === band.id}
                disabled={busy}
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
        </fieldset>

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
  onClose,
  onDone,
}: {
  unit: OrgUnitRead;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const tCommon = useTranslations("common");
  const withStepUp = useStepUp();

  const [name, setName] = useState(unit.name);
  const [confirming, setConfirming] = useState(false);
  const seats = (unit.positions ?? []).filter((p) => p.archived_at === null).length;

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

  const remove = useMutation({
    mutationFn: () => withStepUp(() => archiveUnit(unit.id, unit.version)),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });

  const error = save.error ?? remove.error;
  const busy = save.isPending || remove.isPending;

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
