"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { OrgUnitRead, SupervisorKind } from "@/lib/api/contract";
import { fetchTree } from "@/lib/api/hierarchy";
import { createSupervisor } from "@/lib/api/supervisors";
import { cn } from "@/lib/cn";
import { Alert } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Dialog } from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/**
 * Starting a Supervisor — both kinds of it.
 *
 * §10 gives the product two: *"Personal Supervisor Agent: logically isolated per eligible account;
 * supervises that user's permitted Job Agents"* and *"Department Supervisor Agent: supervises
 * selected users/Agents in a department."* The Supervisor form's first group is *"Identity, owner,
 * department and linked Objective scope"*.
 *
 * The screen offered one. The create control sent `kind: "personal"` as a literal, so half of
 * Gate 6's headline deliverable existed in the database, in the API, in the constraints and in the
 * tests, and could not be reached by anybody using the product. The backend has refused a
 * department Supervisor with no department since migration 0023 and accepted one with a department
 * all along.
 *
 * ## Why a dialog and not another field in the top bar
 *
 * The old form was an inline row in the top bar's action slot, and `topbar.tsx` already carries a
 * note about that slot competing with the search box and the bell between `md` and `lg`. A kind
 * choice and a department picker do not fit there, and squeezing them in would make the one screen
 * that has to explain a governance distinction the most cramped place to read it.
 *
 * ## Why the kind cannot be changed afterwards
 *
 * `SupervisorUpdate` has no `kind` and no `org_node_id`, deliberately: a personal Supervisor that
 * became a department one would silently widen what it watches, and the trigger that makes
 * *personal* mean personal would have to be relaxed to allow it. So this dialog is the only place
 * the decision is made, and it says so rather than letting somebody discover it later.
 */
export function NewSupervisorDialog({
  onCreated,
  onClose,
}: {
  onCreated: (id: string) => void;
  onClose: () => void;
}) {
  const t = useTranslations("supervisor");
  const tCommon = useTranslations("common");
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [kind, setKind] = useState<SupervisorKind>("personal");
  const [department, setDepartment] = useState("");

  //  The chart, for the department picker. Fetched when the dialog opens rather than with the
  //  list behind it: most Supervisors are personal, and a workspace's whole hierarchy is not
  //  something to pull down for a button nobody pressed.
  const tree = useQuery({
    queryKey: ["hierarchy", "tree"],
    queryFn: ({ signal }) => fetchTree({ signal }),
  });
  //  Every node a department Supervisor may name — which is every node except the company at the
  //  top. §10: *"Workspace-wide Supervisor is restricted and may be added later"*, and a
  //  department Supervisor pointed at the company is that by another name. Divisions, departments
  //  and teams are all offered: §10 says "a department" and the chart is where an organisation
  //  decides what its departments are called.
  const units = indentFromTop(
    ordered(tree.data?.units ?? []).filter((unit) => unit.unit_type !== "company"),
  );
  //  A workspace with nothing but a company node has no department to name yet, and that is the
  //  same situation as an empty chart as far as this dialog is concerned.
  const noChart = tree.isSuccess && units.length === 0;

  const create = useMutation({
    mutationFn: () =>
      createSupervisor({
        name: name.trim(),
        kind,
        //  Both halves matter to the backend: a department Supervisor with no department is
        //  refused, and a personal one *with* a department is refused too.
        org_node_id: kind === "department" ? department : null,
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["supervisors"] });
      onCreated(result.id);
    },
  });

  const ready =
    name.trim().length > 0 && (kind === "personal" || department.length > 0);

  return (
    <Dialog
      title={t("newSupervisor")}
      description={t("newSupervisorHelp")}
      onClose={onClose}
      busy={create.isPending}
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) create.mutate();
        }}
      >
        <Field label={t("supervisorName")} htmlFor="new-supervisor-name" required>
          {(field) => (
            <Input
              {...field}
              value={name}
              autoFocus
              placeholder={t("newSupervisorPlaceholder")}
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>

        {/*  A radiogroup, not a dropdown. Two options that mean different things want their
            explanations visible at the same time — a `select` hides the one you did not open. */}
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">{t("kindLabel")}</legend>
          <KindOption
            value="personal"
            chosen={kind === "personal"}
            onChoose={() => {
              setKind("personal");
              setDepartment("");
            }}
            icon={<Eye aria-hidden className="size-4" />}
            title={t("kind.personal")}
            detail={t("kindPersonalHelp")}
          />
          <KindOption
            value="department"
            chosen={kind === "department"}
            onChoose={() => setKind("department")}
            icon={<Users aria-hidden className="size-4" />}
            title={t("kind.department")}
            detail={t("kindDepartmentHelp")}
            //  A department Supervisor with no chart to point at cannot be created, and the
            //  reason is worth saying out loud on a workspace that has not drawn one yet.
            disabled={noChart}
            disabledReason={t("kindDepartmentNoChart")}
          />
        </fieldset>

        {kind === "department" ? (
          <Field label={t("department")} htmlFor="new-supervisor-department" required>
            {(field) => (
              <select
                {...field}
                value={department}
                disabled={tree.isPending || units.length === 0}
                onChange={(event) => setDepartment(event.target.value)}
                className={cn(
                  "h-9 w-full rounded-md border border-border bg-card px-3 text-sm",
                  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)]",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                )}
              >
                <option value="">
                  {tree.isPending ? tCommon("loading") : t("chooseDepartment")}
                </option>
                {units.map((unit) => (
                  <option key={unit.id} value={unit.id}>
                    {`${"— ".repeat(unit.depth)}${unit.name}`}
                  </option>
                ))}
              </select>
            )}
          </Field>
        ) : null}

        {tree.isError && kind === "department" ? (
          <Alert tone="danger" title={t("chartUnavailable")}>
            {(tree.error as Error).message}
          </Alert>
        ) : null}

        {/*  §10 again: the two scopes are independent, and neither is filled in by choosing a
            department. Said here because "department Supervisor" reads like it comes with the
            department's people already in it, and §997 is explicit that it does not. */}
        <p className="text-xs text-muted-foreground">{t("newSupervisorNext")}</p>

        {create.isError ? (
          <Alert tone="danger" title={t("couldNotCreate")}>
            {(create.error as Error).message}
          </Alert>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            {tCommon("cancel")}
          </Button>
          <Button type="submit" variant="primary" busy={create.isPending} disabled={!ready}>
            {t("start")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/**
 * Depth measured from the shallowest node shown, not from the chart's root.
 *
 * The company is filtered out above, so its children are at depth 1 in the tree and are the top
 * level of this list. Indenting every one of them by a dash would suggest a parent that is not
 * there.
 */
function indentFromTop(
  units: (OrgUnitRead & { depth: number })[],
): (OrgUnitRead & { depth: number })[] {
  if (units.length === 0) return units;
  const top = Math.min(...units.map((unit) => unit.depth));
  return units.map((unit) => ({ ...unit, depth: unit.depth - top }));
}

/** One choice, with its consequence next to it. */
function KindOption({
  value,
  chosen,
  onChoose,
  icon,
  title,
  detail,
  disabled = false,
  disabledReason,
}: {
  value: SupervisorKind;
  chosen: boolean;
  onChoose: () => void;
  icon: React.ReactNode;
  title: string;
  detail: string;
  disabled?: boolean;
  disabledReason?: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 rounded-md border p-3 text-sm",
        chosen ? "border-primary bg-[var(--ub-accent-soft,var(--muted))]" : "border-border bg-card",
        disabled && "cursor-not-allowed opacity-60",
        "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--ub-focus)]",
      )}
    >
      <input
        type="radio"
        name="supervisor-kind"
        value={value}
        checked={chosen}
        disabled={disabled}
        onChange={onChoose}
        className="mt-0.5"
      />
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 font-medium">
          {icon}
          {title}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {disabled && disabledReason ? disabledReason : detail}
        </span>
      </span>
    </label>
  );
}

/**
 * The chart flattened for a `select`, parents before children, with a depth to indent by.
 *
 * The API returns units unordered with a `parent_id`, which is right for drawing a tree and wrong
 * for a list somebody reads top to bottom. Walking from the roots also drops any node whose parent
 * is missing from the response — an archived parent, most likely — which is better than showing a
 * seemingly top-level department that is not one.
 */
function ordered(units: OrgUnitRead[]): (OrgUnitRead & { depth: number })[] {
  const children = new Map<string | null, OrgUnitRead[]>();
  for (const unit of units) {
    if (unit.archived_at) continue;
    const key = unit.parent_id ?? null;
    children.set(key, [...(children.get(key) ?? []), unit]);
  }
  for (const list of children.values()) list.sort((a, b) => a.name.localeCompare(b.name));

  const flat: (OrgUnitRead & { depth: number })[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const unit of children.get(parent) ?? []) {
      flat.push({ ...unit, depth });
      walk(unit.id, depth + 1);
    }
  };
  walk(null, 0);
  return flat;
}
