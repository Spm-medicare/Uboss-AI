"use client";

import { Plus, ShieldAlert, Siren, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode } from "react";

import type {
  SupervisorEscalationInput,
  SupervisorEscalationRead,
  NotificationInput,
  NotificationRead,
  PersonRef,
  QualityGateInput,
  QualityGateRead,
} from "@/lib/api/contract";
import { PersonSelect } from "@/ui/builder/person-select";
import { Button, Field, Input, Textarea } from "@/ui";

/**
 * `PLAN.md` §10's groups 6, 8 and 9 — the three that had no editor at all.
 *
 * Each of these is a list the API accepts, the publish summary counts, and the screen sent as a
 * permanently empty array. Two of the three had a consequence beyond the missing fields: the
 * publish warnings `no_quality_gates` and `no_escalations` name something the person is told to
 * fix, and nothing on the screen could fix it. A warning that cannot be cleared teaches people to
 * ignore warnings, which is the opposite of what it is for.
 *
 * ## Why one file and one row shape
 *
 * The three lists are different — a gate has a condition and a failure action, an escalation has a
 * person and a delay, a notification has an event and a channel — but they are added, removed and
 * reordered identically. `RowList` owns that part so the three editors are only their fields, and
 * so a change to how a row is removed happens once.
 */

/** A list of rows with add and remove, and nothing else. */
function RowList<T>({
  title,
  hint,
  icon,
  rows,
  empty,
  disabled,
  addLabel,
  onAdd,
  onRemove,
  complete,
  children,
}: {
  title: string;
  hint: string;
  icon: ReactNode;
  rows: readonly T[];
  /** What to say when the list is empty. Never a blank space: empty is a state, not an absence. */
  empty: string;
  disabled: boolean;
  addLabel: string;
  onAdd: () => void;
  onRemove: (index: number) => void;
  /** Whether a row is complete enough to have been sent. Absent means always. */
  complete?: (row: T) => boolean;
  children: (row: T, index: number) => ReactNode;
}) {
  const t = useTranslations("supervisor");

  return (
    <section className="space-y-3">
      <div className="flex items-start gap-2">
        <span aria-hidden className="mt-0.5 text-muted-foreground">
          {icon}
        </span>
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
          {empty}
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((row, index) => (
            <li
              key={index}
              className="rounded-md border border-border bg-card p-3"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("policy.rowNumber", { number: index + 1 })}
                  {/*  Only while it is incomplete. A row that cannot be sent yet says so, rather
                      than sitting there looking stored. */}
                  {complete && !complete(row) ? (
                    <span className="rounded bg-approval-soft px-1.5 py-0.5 normal-case tracking-normal text-approval">
                      {t("policy.notSavedYet")}
                    </span>
                  ) : null}
                </span>
                {!disabled ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="size-7 px-0 text-muted-foreground hover:text-danger"
                    aria-label={t("policy.removeRow", { number: index + 1 })}
                    onClick={() => onRemove(index)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">{children(row, index)}</div>
            </li>
          ))}
        </ul>
      )}

      {!disabled ? (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          icon={<Plus className="size-3.5" />}
          onClick={onAdd}
        >
          {addLabel}
        </Button>
      ) : null}
    </section>
  );
}


/**
 * Whether a row has enough in it to be sent.
 *
 * These three lists have required fields — an escalation must name a situation, an action, and
 * somebody to reach; the database says the last one outright, with a check constraint whose
 * comment is *"an escalation that names nobody is a rule with no addressee"*. A row is created
 * empty and filled in, so between those two moments it cannot go to the server.
 *
 * It is not dropped. It stays on screen, it says it is not saved yet, and it goes with the next
 * save once it is complete. Filtering silently would be the data loss §6 forbids; showing a row
 * that claims to be stored and is not would be the lie the truthfulness rules forbid. Saying so is
 * neither.
 */
export const isComplete = {
  gate: (row: { name: string; condition: string }) =>
    row.name.trim().length > 0 && row.condition.trim().length > 0,
  escalation: (row: {
    situation: string;
    required_action: string;
    escalate_to_membership_id: string | null;
    escalate_to_label: string | null;
  }) =>
    row.situation.trim().length > 0 &&
    row.required_action.trim().length > 0 &&
    Boolean(row.escalate_to_membership_id ?? (row.escalate_to_label ?? "").trim()),
  notification: (row: { event: string }) => row.event.trim().length > 0,
};

/** Renumber after any change: `position` is the order, and the server validates it is 1..n. */
function renumbered<T extends { position: number }>(rows: T[]): T[] {
  return rows.map((row, index) => ({ ...row, position: index + 1 }));
}

// ------------------------------------------------------------------ §10 group 6

export function QualityGates({
  rows,
  onFailureOptions,
  disabled,
  onChange,
}: {
  rows: readonly QualityGateRead[];
  /** The approved failure actions, served rather than written into this file. */
  onFailureOptions: readonly string[];
  disabled: boolean;
  onChange: (rows: QualityGateInput[]) => void;
}) {
  const t = useTranslations("supervisor");

  const asInput = (list: readonly QualityGateRead[]): QualityGateInput[] =>
    list.map((row) => ({
      position: row.position,
      name: row.name,
      condition: row.condition,
      evidence: row.evidence,
      on_failure: row.on_failure,
    }));

  const set = (index: number, patch: Partial<QualityGateInput>) => {
    const next = asInput(rows);
    next[index] = { ...next[index]!, ...patch };
    onChange(next);
  };

  return (
    <RowList
      title={t("policy.gatesTitle")}
      hint={t("policy.gatesHint")}
      icon={<ShieldAlert className="size-4" />}
      rows={rows}
      empty={t("policy.gatesEmpty")}
      disabled={disabled}
      addLabel={t("policy.addGate")}
      onAdd={() =>
        onChange(
          renumbered([
            ...asInput(rows),
            {
              position: rows.length + 1,
              name: "",
              condition: "",
              evidence: null,
              on_failure: (onFailureOptions[0] ?? "escalate") as QualityGateInput["on_failure"],
            },
          ]),
        )
      }
      onRemove={(index) =>
        onChange(renumbered(asInput(rows).filter((_, at) => at !== index)))
      }
      complete={isComplete.gate}
    >
      {(row, index) => (
        <>
          <Field label={t("policy.gateName")} required>
            {(field) => (
              <Input
                {...field}
                value={row.name}
                disabled={disabled}
                placeholder={t("policy.gateNamePlaceholder")}
                onChange={(event) => set(index, { name: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("policy.onFailure")}>
            {(field) => (
              <select
                {...field}
                value={row.on_failure}
                disabled={disabled}
                onChange={(event) =>
                  set(index, {
                    on_failure: event.target.value as QualityGateInput["on_failure"],
                  })
                }
                className="h-9 w-full rounded-md border border-border bg-card px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {onFailureOptions.map((option) => (
                  <option key={option} value={option}>
                    {t(`onFailure.${option}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <div className="sm:col-span-2">
            <Field label={t("policy.gateCondition")} hint={t("policy.gateConditionHint")} required>
              {(field) => (
                <Textarea
                  {...field}
                  rows={2}
                  value={row.condition}
                  disabled={disabled}
                  onChange={(event) => set(index, { condition: event.target.value })}
                />
              )}
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t("policy.gateEvidence")} hint={t("policy.gateEvidenceHint")}>
              {(field) => (
                <Textarea
                  {...field}
                  rows={2}
                  value={row.evidence ?? ""}
                  disabled={disabled}
                  onChange={(event) => set(index, { evidence: event.target.value || null })}
                />
              )}
            </Field>
          </div>
        </>
      )}
    </RowList>
  );
}

// ------------------------------------------------------------------ §10 group 8

export function Escalations({
  rows,
  people,
  disabled,
  onChange,
}: {
  rows: readonly SupervisorEscalationRead[];
  people: readonly PersonRef[];
  disabled: boolean;
  onChange: (rows: SupervisorEscalationInput[]) => void;
}) {
  const t = useTranslations("supervisor");

  const asInput = (list: readonly SupervisorEscalationRead[]): SupervisorEscalationInput[] =>
    list.map((row) => ({
      position: row.position,
      situation: row.situation,
      required_action: row.required_action,
      escalate_to_membership_id: row.escalate_to_membership_id,
      escalate_to_label: row.escalate_to_label,
      after_minutes: row.after_minutes,
    }));

  const set = (index: number, patch: Partial<SupervisorEscalationInput>) => {
    const next = asInput(rows);
    next[index] = { ...next[index]!, ...patch };
    onChange(next);
  };

  return (
    <RowList
      title={t("policy.escalationsTitle")}
      hint={t("policy.escalationsHint")}
      icon={<Siren className="size-4" />}
      rows={rows}
      empty={t("policy.escalationsEmpty")}
      disabled={disabled}
      addLabel={t("policy.addEscalation")}
      onAdd={() =>
        onChange(
          renumbered([
            ...asInput(rows),
            {
              position: rows.length + 1,
              situation: "",
              required_action: "",
              escalate_to_membership_id: null,
              escalate_to_label: null,
              after_minutes: null,
            },
          ]),
        )
      }
      onRemove={(index) =>
        onChange(renumbered(asInput(rows).filter((_, at) => at !== index)))
      }
      complete={isComplete.escalation}
    >
      {(row, index) => (
        <>
          <Field label={t("policy.situation")} required>
            {(field) => (
              <Input
                {...field}
                value={row.situation}
                disabled={disabled}
                placeholder={t("policy.situationPlaceholder")}
                onChange={(event) => set(index, { situation: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("policy.afterMinutes")} hint={t("policy.afterMinutesHint")}>
            {(field) => (
              <Input
                {...field}
                type="number"
                min={0}
                value={row.after_minutes ?? ""}
                disabled={disabled}
                onChange={(event) =>
                  set(index, {
                    after_minutes: event.target.value ? Number(event.target.value) : null,
                  })
                }
              />
            )}
          </Field>
          <div className="sm:col-span-2">
            <Field label={t("policy.requiredAction")} required>
              {(field) => (
                <Textarea
                  {...field}
                  rows={2}
                  value={row.required_action}
                  disabled={disabled}
                  onChange={(event) => set(index, { required_action: event.target.value })}
                />
              )}
            </Field>
          </div>
          {/*  A person, and a label beside it for the case the sheet named a role. Same split as
              the approver: an escalation that names only a role has nobody to reach. */}
          <PersonSelect
            label={t("policy.escalateTo")}
            hint={t("policy.escalateToHint")}
            required
            value={row.escalate_to_membership_id}
            people={people as PersonRef[]}
            disabled={disabled}
            onChange={(value) => set(index, { escalate_to_membership_id: value })}
          />
          <Field label={t("policy.escalateToLabel")}>
            {(field) => (
              <Input
                {...field}
                value={row.escalate_to_label ?? ""}
                disabled={disabled}
                onChange={(event) =>
                  set(index, { escalate_to_label: event.target.value || null })
                }
              />
            )}
          </Field>
        </>
      )}
    </RowList>
  );
}

// ------------------------------------------------------------------ §10 group 9

export function Notifications({
  rows,
  people,
  disabled,
  onChange,
}: {
  rows: readonly NotificationRead[];
  people: readonly PersonRef[];
  disabled: boolean;
  onChange: (rows: NotificationInput[]) => void;
}) {
  const t = useTranslations("supervisor");

  const asInput = (list: readonly NotificationRead[]): NotificationInput[] =>
    list.map((row) => ({
      position: row.position,
      event: row.event,
      channel: row.channel,
      to_handlers: row.to_handlers,
      recipient_membership_id: row.recipient_membership_id,
      recipient_label: row.recipient_label,
    }));

  const set = (index: number, patch: Partial<NotificationInput>) => {
    const next = asInput(rows);
    next[index] = { ...next[index]!, ...patch };
    onChange(next);
  };

  return (
    <RowList
      title={t("policy.notificationsTitle")}
      hint={t("policy.notificationsHint")}
      icon={<Siren className="size-4" />}
      rows={rows}
      empty={t("policy.notificationsEmpty")}
      disabled={disabled}
      addLabel={t("policy.addNotification")}
      onAdd={() =>
        onChange(
          renumbered([
            ...asInput(rows),
            {
              position: rows.length + 1,
              event: "",
              channel: null,
              to_handlers: true,
              recipient_membership_id: null,
              recipient_label: null,
            },
          ]),
        )
      }
      onRemove={(index) =>
        onChange(renumbered(asInput(rows).filter((_, at) => at !== index)))
      }
      complete={isComplete.notification}
    >
      {(row, index) => (
        <>
          <Field label={t("policy.event")} hint={t("policy.eventHint")} required>
            {(field) => (
              <Input
                {...field}
                value={row.event}
                disabled={disabled}
                placeholder={t("policy.eventPlaceholder")}
                onChange={(event) => set(index, { event: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("policy.channel")} hint={t("policy.channelHint")}>
            {(field) => (
              <Input
                {...field}
                value={row.channel ?? ""}
                disabled={disabled}
                onChange={(event) => set(index, { channel: event.target.value || null })}
              />
            )}
          </Field>
          <div className="sm:col-span-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={row.to_handlers}
                disabled={disabled}
                className="size-4 rounded border-border"
                onChange={(event) => set(index, { to_handlers: event.target.checked })}
              />
              {t("policy.toHandlers")}
            </label>
          </div>
          {/*  Somebody in particular, on top of the handlers. Both may be set: a run that fails at
              two in the morning goes to whoever is watching *and* to the person who asked to know. */}
          <PersonSelect
            label={t("policy.recipient")}
            hint={t("policy.recipientHint")}
            value={row.recipient_membership_id}
            people={people as PersonRef[]}
            disabled={disabled}
            onChange={(value) => set(index, { recipient_membership_id: value })}
          />
          <Field label={t("policy.recipientLabel")}>
            {(field) => (
              <Input
                {...field}
                value={row.recipient_label ?? ""}
                disabled={disabled}
                onChange={(event) =>
                  set(index, { recipient_label: event.target.value || null })
                }
              />
            )}
          </Field>
        </>
      )}
    </RowList>
  );
}
