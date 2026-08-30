"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  ChevronRight,
  LayoutGrid,
  List,
  Pencil,
  Plus,
  Undo2,
  Upload,
  UserPlus,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { OrgUnitRead, PositionRead, UnitType } from "@/lib/api/contract";
import {
  archivePosition,
  archiveUnit,
  createPosition,
  createUnit,
  fetchIssues,
  fetchRevisions,
  fetchTree,
  undoRevision,
} from "@/lib/api/hierarchy";
import { can } from "@/lib/api/auth";
import { cn } from "@/lib/cn";
import { useSession } from "@/lib/auth/use-session";
import { contextFor, formatDateTime } from "@/lib/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  QueryStates,
} from "@/ui";
import { useStepUp } from "@/ui/auth/step-up";
import { AddUnderDialog } from "@/ui/hierarchy/add-under";
import { EditSeatDialog, EditUnitDialog } from "@/ui/hierarchy/edit-seat";
import { OrgChart } from "@/ui/hierarchy/org-chart";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * The company tree — PLAN §5.
 *
 * Three things on this screen exist because the plan names them and they are the ones a chart
 * usually gets wrong:
 *
 * **Vacant seats are shown as vacant.** A position exists whether or not somebody is in it. A
 * chart that only draws people hides the empty seats, and the empty seats are the hiring plan.
 *
 * **Everything is as at one date.** The whole page answers for the same day, so a structure
 * taking effect next month can be looked at without mixing it with today's.
 *
 * **A control is only shown when the person can use it, and it is never the check.** The server
 * re-resolves every permission; hiding a button spares somebody a refusal they could do nothing
 * about, and nothing more than that.
 */
export default function HierarchyPage() {
  const t = useTranslations("hierarchy");
  const tCommon = useTranslations("common");
  const { user } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  //  One date for the whole page. Held here rather than in each panel so the tree, the issues
  //  and the chart can never disagree about which day they are describing.
  const [asAt, setAsAt] = useState(() => new Date().toISOString().slice(0, 10));

  //  Chart or list. The chart answers "what shape is this organisation"; the list is where the
  //  work is done, because it holds the controls and stays readable at four hundred nodes.
  //  Chart first: somebody opening this screen is nearly always asking the first question.
  const [view, setView] = useState<"chart" | "list">("chart");

  //  Which `+` was pressed. One piece of state for the whole chart: a dialog mounted per box
  //  would be sixteen forms on a chart of sixteen people, all but one of them hidden.
  const [adding, setAdding] = useState<{
    unit: OrgUnitRead;
    reportsTo?: PositionRead;
  } | null>(null);
  const [editingSeat, setEditingSeat] = useState<PositionRead | null>(null);
  const [editingUnit, setEditingUnit] = useState<OrgUnitRead | null>(null);

  const tree = useQuery({
    queryKey: ["hierarchy", "tree", asAt],
    queryFn: ({ signal }) => fetchTree({ asAt, signal }),
  });
  const issues = useQuery({
    queryKey: ["hierarchy", "issues", asAt],
    queryFn: ({ signal }) => fetchIssues({ asAt, signal }),
  });
  const revisions = useQuery({
    queryKey: ["hierarchy", "revisions"],
    queryFn: ({ signal }) => fetchRevisions({ limit: 15, signal }),
  });

  const mayEdit = can(user, "administer");
  const mayAssign = can(user, "assign");

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["hierarchy"] });
  }

  return (
    <AppShell
      title={t("title")}
      action={
        //  Import is offered on an empty tree too. A first structure is exactly the one most
        //  likely to arrive as a spreadsheet, and the empty state used to hide the route to it.
        mayEdit && tree.data ? (
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              icon={<Upload className="size-3.5" />}
              onClick={() => router.push("/hierarchy/import")}
            >
              {t("import")}
            </Button>
            {tree.data.is_empty ? null : (
              <AddUnitButton parentId={rootId(tree.data.units)} onDone={refresh} />
            )}
          </div>
        ) : undefined
      }
    >
      {/*  `max-w-5xl` on the reading column, and the chart steps out of it below. A chart is as
          wide as the organisation; a column meant for prose is the wrong container for one. */}
      <div className="mx-auto max-w-5xl space-y-6">
        {/*  A heading on the page, not only in the top bar. The bar names the room; a person
            landing here needs to be told what the screen is for before they are asked to pick a
            date, and a screen that opens with a form control reads as a fragment of something
            else. */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-[1.5rem] font-bold leading-tight tracking-tight">
              {t("heading")}
            </h2>
            <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
              {t("intro")}
            </p>
          </div>
          <div className="flex shrink-0 items-end gap-3">
            {/*  Only offered once there is something to look at. A view switch above an empty
                state is two ways to see nothing. */}
            {tree.data && !tree.data.is_empty ? (
              <ViewSwitch value={view} onChange={setView} />
            ) : null}
            <div className="w-44">
              <Field label={t("asAt")} htmlFor="as-at" required>
                {(field) => (
                  <Input
                    {...field}
                    type="date"
                    value={asAt}
                    onChange={(event) => setAsAt(event.target.value)}
                  />
                )}
              </Field>
            </div>
          </div>
        </div>

        <QueryStates
          isPending={tree.isPending}
          error={tree.error}
          onRetry={() => void tree.refetch()}
        >
          {tree.data?.is_empty ? (
            <NoTreeYet mayEdit={mayEdit} onDone={refresh} />
          ) : (
            <>
              {issues.data && issues.data.length > 0 ? (
                <Issues issues={issues.data} />
              ) : null}

              {view === "chart" ? (
                //  Out of the reading column and across the whole screen. A chart is as wide as
                //  the organisation, and a 64rem column meant a company with five departments
                //  scrolling sideways inside a box a third of the window — on a monitor with
                //  room to show the whole thing. The margins cancel this column's own centring
                //  and the shell's padding, so the chart starts where the sidebar ends.
                <div className="-mx-4 w-[calc(100%+2rem)] sm:-mx-6 sm:w-[calc(100%+3rem)]">
                <OrgChart
                  units={tree.data?.units ?? []}
                  //  One `+` per box and one per seat, both opening the same dialog. Passed only
                  //  when this person may edit, so the chart never has to decide.
                  {...(mayEdit
                    ? {
                        actions: (unit: OrgUnitRead) => (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              icon={<Plus className="size-3.5" />}
                              onClick={() => setAdding({ unit })}
                            >
                              {t("addUnder")}
                            </Button>
                            {/*  The company itself has no Edit: renaming it is renaming the
                                workspace, which belongs in settings rather than on a chart. */}
                            {unit.parent_id === null ? null : (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={<Pencil className="size-3.5" />}
                                onClick={() => setEditingUnit(unit)}
                              >
                                {tCommon("edit")}
                              </Button>
                            )}
                          </>
                        ),
                        seatEdit: (position: PositionRead) => setEditingSeat(position),
                        seatAction: (position: PositionRead) => {
                          const owner = (tree.data?.units ?? []).find(
                            (candidate) => candidate.id === position.org_unit_id,
                          );
                          if (owner) setAdding({ unit: owner, reportsTo: position });
                        },
                      }
                    : {})}
                />
                </div>
              ) : (
                <Tree
                  units={tree.data?.units ?? []}
                  mayEdit={mayEdit}
                  mayAssign={mayAssign}
                  onDone={refresh}
                />
              )}
            </>
          )}
        </QueryStates>

        {editingSeat ? (
          <EditSeatDialog
            position={editingSeat}
            units={tree.data?.units ?? []}
            onClose={() => setEditingSeat(null)}
            onDone={refresh}
          />
        ) : null}

        {editingUnit ? (
          <EditUnitDialog
            unit={editingUnit}
            onClose={() => setEditingUnit(null)}
            onDone={refresh}
          />
        ) : null}

        {adding ? (
          <AddUnderDialog
            unit={adding.unit}
            units={tree.data?.units ?? []}
            reportsTo={adding.reportsTo}
            onClose={() => setAdding(null)}
            onDone={refresh}
          />
        ) : null}

        <History
          isPending={revisions.isPending}
          error={revisions.error}
          revisions={revisions.data?.revisions ?? []}
          mayUndo={mayEdit}
          timeZone={user?.timezone}
          onDone={refresh}
        />
      </div>
    </AppShell>
  );
}

/**
 * Chart or list.
 *
 * A segmented control rather than two buttons: they are one choice with two answers, and the
 * shape says so. `aria-pressed` carries the state, and each has a `title` because the labels are
 * icons — `ui/README.md` requires an icon-only control to have one.
 */
function ViewSwitch({
  value,
  onChange,
}: {
  value: "chart" | "list";
  onChange: (next: "chart" | "list") => void;
}) {
  const t = useTranslations("hierarchy");

  return (
    <div
      role="group"
      aria-label={t("viewLabel")}
      className="flex gap-1 rounded-lg border border-border bg-muted p-1"
    >
      {(
        [
          ["chart", LayoutGrid],
          ["list", List],
        ] as const
      ).map(([option, Icon]) => (
        <button
          key={option}
          type="button"
          aria-pressed={value === option}
          title={t(`view.${option}`)}
          onClick={() => onChange(option)}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium",
            "transition-colors duration-150 motion-reduce:transition-none",
            "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
            value === option
              ? "bg-card text-foreground shadow-sm ring-1 ring-inset ring-border"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon aria-hidden className="size-3.5" />
          {t(`view.${option}`)}
        </button>
      ))}
    </div>
  );
}

/**
 * What is worth looking at, without burying the chart it is about.
 *
 * Every vacant seat is an issue, correctly — a vacancy is the thing somebody scanning a structure
 * is looking for. But a new company is *all* vacancies, so the banner listing them was ten lines
 * tall and sat above the chart that shows the same thing in colour. It now shows the first few
 * and counts the rest.
 *
 * The count is never rounded and the list is never truncated silently: "and 7 more" is a fact,
 * and the button that reveals them is right there.
 */
function Issues({ issues }: { issues: { kind: string; entity_id: string; detail: string }[] }) {
  const t = useTranslations("hierarchy");
  const [all, setAll] = useState(false);
  const SHOWN = 3;
  const visible = all ? issues : issues.slice(0, SHOWN);
  const hidden = issues.length - visible.length;

  return (
    <Alert tone="warning" title={t("issuesTitle", { count: issues.length })}>
      <ul className="mt-1 space-y-0.5">
        {visible.map((issue) => (
          <li key={`${issue.kind}:${issue.entity_id}`}>{issue.detail}</li>
        ))}
      </ul>
      {hidden > 0 || all ? (
        <Button
          size="sm"
          variant="ghost"
          className="mt-1.5 px-0 underline underline-offset-4 hover:bg-transparent"
          onClick={() => setAll(!all)}
        >
          {all ? t("issuesFewer") : t("issuesMore", { count: hidden })}
        </Button>
      ) : null}
    </Alert>
  );
}

/** The root is the one unit with no parent. The database guarantees there is at most one. */
function rootId(units: OrgUnitRead[]): string | null {
  return units.find((unit) => unit.parent_id === null)?.id ?? null;
}

/**
 * Nothing here yet.
 *
 * Distinct from a failure, and it says what to do next. An organisation with no tree is the
 * normal first minute of using the product, not a problem.
 */
function NoTreeYet({ mayEdit, onDone }: { mayEdit: boolean; onDone: () => void }) {
  const t = useTranslations("hierarchy");
  const [name, setName] = useState("");
  const withStepUp = useStepUp();
  const create = useMutation({
    mutationFn: () =>
      withStepUp(() =>
        createUnit({ name, unit_type: "company" as UnitType, parent_id: null }),
      ),
    onSuccess: onDone,
  });

  return (
    <Card>
      <CardBody className="space-y-4 py-10 text-center">
        <Building2 aria-hidden className="mx-auto size-8 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">{t("emptyTitle")}</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
            {mayEdit ? t("emptyBody") : t("emptyBodyReadOnly")}
          </p>
        </div>

        {mayEdit ? (
          <form
            className="mx-auto flex max-w-sm items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <div className="flex-1 text-left">
              <Field label={t("companyName")} htmlFor="company-name" required>
                {(field) => (
                  <Input
                    {...field}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    autoComplete="organization"
                  />
                )}
              </Field>
            </div>
            <Button
              type="submit"
              variant="primary"
              busy={create.isPending}
              disabled={!name.trim()}
            >
              {t("createCompany")}
            </Button>
          </form>
        ) : null}

        {mayEdit ? (
          <p className="text-sm text-muted-foreground">
            {t("orImport")}{" "}
            <Link
              href="/hierarchy/import"
              className="text-primary underline underline-offset-4"
            >
              {t("importOne")}
            </Link>
          </p>
        ) : null}

        {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
      </CardBody>
    </Card>
  );
}

/**
 * The tree, built from the flat list.
 *
 * The server sends `parent_id` and nothing nested, so the nesting is decided here — which means
 * one response serves this view and a search result without the server guessing.
 */
function Tree({
  units,
  mayEdit,
  mayAssign,
  onDone,
}: {
  units: OrgUnitRead[];
  mayEdit: boolean;
  mayAssign: boolean;
  onDone: () => void;
}) {
  const childrenByParent = useMemo(() => {
    const map = new Map<string | null, OrgUnitRead[]>();
    for (const unit of units) {
      const bucket = map.get(unit.parent_id) ?? [];
      bucket.push(unit);
      map.set(unit.parent_id, bucket);
    }
    return map;
  }, [units]);

  const roots = childrenByParent.get(null) ?? [];

  return (
    <ul className="space-y-3">
      {roots.map((unit) => (
        <UnitNode
          key={unit.id}
          unit={unit}
          childrenByParent={childrenByParent}
          depth={0}
          mayEdit={mayEdit}
          mayAssign={mayAssign}
          onDone={onDone}
        />
      ))}
    </ul>
  );
}

function UnitNode({
  unit,
  childrenByParent,
  depth,
  mayEdit,
  mayAssign,
  onDone,
}: {
  unit: OrgUnitRead;
  //  Not named `children`: React reserves that prop, and a Map passed under it is both a lint
  //  error and a genuinely confusing thing to read.
  childrenByParent: Map<string | null, OrgUnitRead[]>;
  depth: number;
  mayEdit: boolean;
  mayAssign: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const [open, setOpen] = useState(depth < 2);
  const sub = childrenByParent.get(unit.id) ?? [];
  //  The generated contract has `positions` optional — the server always sends it, but a client
  //  that trusts a server's "always" is a client that crashes the day it stops being true.
  const positions = unit.positions ?? [];
  const withStepUp = useStepUp();
  const archive = useMutation({
    mutationFn: () => withStepUp(() => archiveUnit(unit.id, unit.version)),
    onSuccess: onDone,
  });

  return (
    <li>
      <Card>
        <CardHeader
          title={unit.name}
          description={unit.external_ref ?? undefined}
          action={
            <div className="flex shrink-0 items-center gap-1.5">
              <Badge tone="neutral">{t(`unitType.${unit.unit_type}`)}</Badge>
              {mayEdit ? (
                <>
                  <AddUnitButton parentId={unit.id} onDone={onDone} />
                  <AddPositionButton unitId={unit.id} onDone={onDone} />
                  <Button
                    size="sm"
                    variant="ghost"
                    busy={archive.isPending}
                    onClick={() => archive.mutate()}
                  >
                    {t("archive")}
                  </Button>
                </>
              ) : null}
            </div>
          }
        />

        {archive.error ? (
          <CardBody className="pb-0">
            <Alert tone="danger">{archive.error.message}</Alert>
          </CardBody>
        ) : null}

        <CardBody className="space-y-2">
          {positions.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noPositions")}</p>
          ) : (
            <ul className="space-y-1.5">
              {positions.map((position) => (
                <PositionRow
                  key={position.id}
                  position={position}
                  mayEdit={mayEdit}
                  mayAssign={mayAssign}
                  onDone={onDone}
                />
              ))}
            </ul>
          )}

          {sub.length > 0 ? (
            <div className="pt-1">
              <Button
                size="sm"
                variant="ghost"
                className="px-0"
                aria-expanded={open}
                onClick={() => setOpen(!open)}
                icon={
                  <ChevronRight
                    className={`size-3.5 transition-transform duration-150 motion-reduce:transition-none ${
                      open ? "rotate-90" : ""
                    }`}
                  />
                }
              >
                {t("subUnits", { count: sub.length })}
              </Button>
              {open ? (
                <ul className="mt-2 space-y-3 border-l border-border pl-4">
                  {sub.map((child) => (
                    <UnitNode
                      key={child.id}
                      unit={child}
                      childrenByParent={childrenByParent}
                      depth={depth + 1}
                      mayEdit={mayEdit}
                      mayAssign={mayAssign}
                      onDone={onDone}
                    />
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </CardBody>
      </Card>
    </li>
  );
}

/**
 * One seat.
 *
 * A vacant seat says so in words as well as in colour — `ui/README.md` forbids colour-only
 * status, and "vacant" is exactly the state somebody scanning the chart is looking for.
 */
function PositionRow({
  position,
  mayEdit,
  mayAssign,
  onDone,
}: {
  position: PositionRead;
  mayEdit: boolean;
  mayAssign: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const withStepUp = useStepUp();
  const archive = useMutation({
    mutationFn: () => withStepUp(() => archivePosition(position.id, position.version)),
    onSuccess: onDone,
  });

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{position.title}</p>
        <p className="truncate text-xs text-muted-foreground">
          {position.holder ? position.holder.display_name : t("vacant")}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {position.holder ? (
          <Badge tone="human">{t("filled")}</Badge>
        ) : (
          <Badge tone="approval">{t("vacant")}</Badge>
        )}
        {mayAssign && !position.holder ? (
          <AssignButton position={position} onDone={onDone} />
        ) : null}
        {mayEdit ? (
          <Button
            size="sm"
            variant="ghost"
            busy={archive.isPending}
            onClick={() => archive.mutate()}
          >
            {t("archive")}
          </Button>
        ) : null}
      </div>
      {archive.error ? (
        <div className="w-full">
          <Alert tone="danger">{archive.error.message}</Alert>
        </div>
      ) : null}
    </li>
  );
}

function AddUnitButton({
  parentId,
  onDone,
}: {
  parentId: string | null;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const withStepUp = useStepUp();
  const create = useMutation({
    mutationFn: () =>
      withStepUp(() =>
        createUnit({
          name,
          unit_type: "department" as UnitType,
          parent_id: parentId,
        }),
      ),
    onSuccess: () => {
      setName("");
      setOpen(false);
      onDone();
    },
  });

  if (!open) {
    return (
      <Button
        size="sm"
        variant="ghost"
        icon={<Plus className="size-3.5" />}
        onClick={() => setOpen(true)}
      >
        {t("addDepartment")}
      </Button>
    );
  }

  return (
    <form
      className="flex items-end gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <Input
        aria-label={t("departmentName")}
        value={name}
        autoFocus
        onChange={(event) => setName(event.target.value)}
        className="h-8 w-44 text-sm"
      />
      <Button
        type="submit"
        size="sm"
        variant="primary"
        busy={create.isPending}
        disabled={!name.trim()}
      >
        {t("add")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        {t("cancel")}
      </Button>
    </form>
  );
}

function AddPositionButton({ unitId, onDone }: { unitId: string; onDone: () => void }) {
  const t = useTranslations("hierarchy");
  const [title, setTitle] = useState("");
  const [open, setOpen] = useState(false);
  const withStepUp = useStepUp();
  const create = useMutation({
    mutationFn: () => withStepUp(() => createPosition({ org_unit_id: unitId, title })),
    onSuccess: () => {
      setTitle("");
      setOpen(false);
      onDone();
    },
  });

  if (!open) {
    return (
      <Button
        size="sm"
        variant="ghost"
        icon={<Plus className="size-3.5" />}
        onClick={() => setOpen(true)}
      >
        {t("addPosition")}
      </Button>
    );
  }

  return (
    <form
      className="flex items-end gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <Input
        aria-label={t("positionTitle")}
        value={title}
        autoFocus
        onChange={(event) => setTitle(event.target.value)}
        className="h-8 w-44 text-sm"
      />
      <Button
        type="submit"
        size="sm"
        variant="primary"
        busy={create.isPending}
        disabled={!title.trim()}
      >
        {t("add")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        {t("cancel")}
      </Button>
    </form>
  );
}

/**
 * Put the signed-in person into a seat.
 *
 * Only themselves, for now, and the label says so. Choosing a colleague needs a list of people
 * in the workspace, and that endpoint does not exist yet — a picker fed by anything else would
 * be inventing names.
 */
function AssignButton({
  position,
  onDone,
}: {
  position: PositionRead;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const { user } = useSession();
  const withStepUp = useStepUp();
  const assign = useMutation({
    mutationFn: async () => {
      const { assignPerson } = await import("@/lib/api/hierarchy");
      return withStepUp(() =>
        assignPerson(position.id, {
          membership_id: user!.membership_id,
          effective_from: new Date().toISOString().slice(0, 10),
        }),
      );
    },
    onSuccess: onDone,
  });

  if (!user) return null;

  return (
    <Button
      size="sm"
      variant="ghost"
      busy={assign.isPending}
      icon={<UserPlus className="size-3.5" />}
      onClick={() => assign.mutate()}
      title={t("assignMeHint")}
    >
      {t("assignMe")}
    </Button>
  );
}

/**
 * What changed, and who changed it — PLAN §5's revision history.
 *
 * Undo appears only on a change that can actually be reversed. `can_undo` comes from the server,
 * which knows both whether the change type is reversible and whether anything has happened
 * since; guessing either here would put a button on a request that is going to be refused.
 */
function History({
  isPending,
  error,
  revisions,
  mayUndo,
  timeZone,
  onDone,
}: {
  isPending: boolean;
  error: Error | null;
  revisions: { id: string; summary: string; created_at: string; can_undo: boolean;
    actor_display_name: string | null }[];
  mayUndo: boolean;
  timeZone: string | undefined;
  onDone: () => void;
}) {
  const t = useTranslations("hierarchy");
  const format = contextFor(timeZone);
  const withStepUp = useStepUp();
  const undo = useMutation({
    mutationFn: (id: string) => withStepUp(() => undoRevision(id)),
    onSuccess: onDone,
  });

  return (
    <Card as="section">
      <CardHeader title={t("historyTitle")} description={t("historySubtitle")} />
      <QueryStates
        isPending={isPending}
        error={error}
        isEmpty={revisions.length === 0}
        emptyTitle={t("historyEmpty")}
      >
        <ul className="divide-y divide-border">
          {revisions.map((revision) => (
            <li
              key={revision.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm">{revision.summary}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {revision.actor_display_name ?? t("unknownActor")} ·{" "}
                  {formatDateTime(revision.created_at, format)}
                </p>
              </div>
              {mayUndo && revision.can_undo ? (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Undo2 className="size-3.5" />}
                  busy={undo.isPending && undo.variables === revision.id}
                  onClick={() => undo.mutate(revision.id)}
                >
                  {t("undo")}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      </QueryStates>
      {undo.error ? (
        <CardBody>
          <Alert tone="danger">{undo.error.message}</Alert>
        </CardBody>
      ) : null}
    </Card>
  );
}
