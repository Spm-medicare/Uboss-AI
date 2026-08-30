"use client";

import { KeyRound, Plus, ShieldCheck, Trash2, UserCog, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type {
  HandlerRead,
  SupervisedInput,
  SupervisedRead,
} from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Alert, Badge, Button, Field, Input } from "@/ui";

/**
 * `PLAN.md` §10's two scopes, drawn as two sections that do not share a control.
 *
 * > Two independent scopes are mandatory:
 * > 1. Supervised members/Agents: whose Agents are monitored?
 * > 2. Allowed handlers: who may control this Supervisor?
 *
 * The separation is not a layout choice. Adding somebody to one must never add them to the other,
 * and the surest way to keep that true on a screen is for there to be no control that could do
 * both — no "add person" that asks which list afterwards, no shared row. They are also saved by
 * different calls behind different permissions, so a person who may edit one may genuinely be
 * unable to touch the other, and the screen has to be able to show that.
 */

// ------------------------------------------------------------------ scope 1

export function SupervisedScope({
  rows,
  disabled,
  onChange,
}: {
  rows: SupervisedRead[];
  disabled: boolean;
  onChange: (next: SupervisedInput[]) => void;
}) {
  const t = useTranslations("supervisor");
  const [personId, setPersonId] = useState("");

  const asInput = (list: SupervisedRead[]): SupervisedInput[] =>
    list.map((row, index) => ({
      position: index + 1,
      membership_id: row.membership_id,
      agent_id: row.agent_id,
      agent_version_id: row.agent_version_id,
    }));

  return (
    <section aria-labelledby="scope-supervised" className="space-y-3">
      <div className="flex items-center gap-2">
        <Users aria-hidden className="size-4 text-muted-foreground" />
        <h3 id="scope-supervised" className="text-sm font-semibold">
          {t("scope.supervised")}
        </h3>
      </div>
      <p className="text-sm text-muted-foreground">{t("scope.supervisedHint")}</p>

      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {t("scope.nothingSupervised")}
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((row, index) => (
            <li
              key={row.id}
              className="flex items-center gap-3 rounded-lg border border-border bg-card p-3"
            >
              <span className="grid size-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
                {row.position}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {row.person_name ?? row.membership_id}
                </p>
                <p className="text-xs text-muted-foreground">
                  {/*  Null means every Agent that person owns, now and later — a real difference
                      worth saying rather than showing an empty cell. */}
                  {row.agent_name
                    ? t("scope.oneAgent", { name: row.agent_name })
                    : t("scope.allTheirAgents")}
                </p>
              </div>
              {!disabled ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 className="size-3.5" />}
                  onClick={() =>
                    onChange(asInput(rows.filter((_, at) => at !== index)))
                  }
                >
                  <span className="sr-only">{t("scope.remove")}</span>
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {!disabled ? (
        <form
          className="flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!personId.trim()) return;
            onChange([
              ...asInput(rows),
              {
                position: rows.length + 1,
                membership_id: personId.trim(),
                agent_id: null,
                agent_version_id: null,
              },
            ]);
            setPersonId("");
          }}
        >
          <div className="flex-1">
            <Field
              label={t("scope.addSupervised")}
              htmlFor="add-supervised"
              hint={t("scope.addSupervisedHint")}
            >
              {(field) => (
                <Input
                  {...field}
                  value={personId}
                  placeholder={t("scope.membershipIdPlaceholder")}
                  onChange={(event) => setPersonId(event.target.value)}
                />
              )}
            </Field>
          </div>
          <Button type="submit" variant="secondary" icon={<Plus className="size-3.5" />}>
            {t("scope.add")}
          </Button>
        </form>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ scope 2

export function HandlerScope({
  rows,
  roles,
  mayManage,
  ownerName,
  busy,
  onSet,
  onRemove,
}: {
  rows: HandlerRead[];
  roles: string[];
  /** From the server's `my_actions`, not worked out here. */
  mayManage: boolean;
  ownerName: string | null;
  busy: string | null;
  onSet: (membershipId: string, role: string) => void;
  onRemove: (membershipId: string) => void;
}) {
  const t = useTranslations("supervisor");
  const [personId, setPersonId] = useState("");
  const [role, setRole] = useState(roles[0] ?? "viewer");

  return (
    <section aria-labelledby="scope-handlers" className="space-y-3">
      <div className="flex items-center gap-2">
        <UserCog aria-hidden className="size-4 text-muted-foreground" />
        <h3 id="scope-handlers" className="text-sm font-semibold">
          {t("scope.handlers")}
        </h3>
      </div>
      <p className="text-sm text-muted-foreground">{t("scope.handlersHint")}</p>

      {/*  The owner holds every handler permission without a row. Saying so beats an empty list
          that reads as "nobody can control this". */}
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 p-3">
        <ShieldCheck aria-hidden className="size-4 text-success" />
        <p className="text-sm">
          {t("scope.ownerIsOwner", { name: ownerName ?? t("scope.theOwner") })}
        </p>
      </div>

      {rows.length > 0 ? (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex items-center gap-3 rounded-lg border border-border bg-card p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {row.person_name ?? row.membership_id}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("scope.grantedOn", {
                    when: new Date(row.granted_at).toLocaleDateString(),
                  })}
                </p>
              </div>
              <Badge tone="neutral">{t(`role.${row.role}`)}</Badge>
              {mayManage ? (
                <Button
                  variant="ghost"
                  size="sm"
                  busy={busy === row.membership_id}
                  icon={<Trash2 className="size-3.5" />}
                  onClick={() => onRemove(row.membership_id)}
                >
                  <span className="sr-only">{t("scope.remove")}</span>
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {mayManage ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!personId.trim()) return;
            onSet(personId.trim(), role);
            setPersonId("");
          }}
        >
          <div className="min-w-48 flex-1">
            <Field label={t("scope.addHandler")} htmlFor="add-handler">
              {(field) => (
                <Input
                  {...field}
                  value={personId}
                  placeholder={t("scope.membershipIdPlaceholder")}
                  onChange={(event) => setPersonId(event.target.value)}
                />
              )}
            </Field>
          </div>
          <Field label={t("scope.role")} htmlFor="handler-role">
            {(field) => (
              <select
                {...field}
                value={role}
                onChange={(event) => setRole(event.target.value)}
                className="h-9 rounded-md border border-border bg-card px-2 text-sm"
              >
                {roles.map((option) => (
                  <option key={option} value={option}>
                    {t(`role.${option}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Button type="submit" variant="secondary" icon={<KeyRound className="size-3.5" />}>
            {t("scope.grant")}
          </Button>
        </form>
      ) : (
        /*  Not hidden. A person who cannot manage handlers should be able to see that this is
            somebody else's decision rather than a feature that does not exist. */
        <Alert tone="info">{t("scope.cannotManageHandlers")}</Alert>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ what cannot act yet

export function RuntimeControls({ className }: { className?: string }) {
  const t = useTranslations("supervisor");

  return (
    <div className={cn("rounded-lg border border-dashed border-border p-4", className)}>
      <p className="text-sm font-medium">{t("runtime.title")}</p>
      <p className="mt-1 text-sm text-muted-foreground">{t("runtime.body")}</p>
      {/*  Disabled and labelled, never shown working. §10 lists monitoring, pause/resume and safe
          retry as capabilities; the runtime that performs them is Gate 7, and a control that
          looked live would be a control that does not do what it says. */}
      <div className="mt-3 flex flex-wrap gap-2">
        {(["monitor", "pause", "resume", "retry"] as const).map((control) => (
          <Button key={control} variant="secondary" size="sm" disabled>
            {t(`runtime.${control}`)}
          </Button>
        ))}
      </div>
    </div>
  );
}
