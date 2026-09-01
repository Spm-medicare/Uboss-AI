"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Save, Send, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";

import type { PersonRef, SimulationInput, SupervisorUpdate } from "@/lib/api/contract";
import {
  fetchSimulations,
  fetchSupervisor,
  fetchSupervisorLists,
  fetchSupervisorPublishSummary,
  fetchSupervisorVersions,
  publishSupervisor,
  removeHandler,
  saveSimulations,
  saveSupervisor,
  setHandler,
  submitSupervisor,
  withdrawSupervisor,
  type Supervisor,
  type SupervisorVocabulary,
} from "@/lib/api/supervisors";
import { fetchPeople } from "@/lib/api/objectives";
import { unsavedSince } from "@/lib/builder/unsaved-since";
import { useAdoptServerVersion } from "@/lib/builder/use-adopt-server-version";
import { useAutosave } from "@/lib/builder/use-autosave";
import { useSession } from "@/lib/auth/use-session";
import { contextFor, formatDate } from "@/lib/format";
import { Alert, Badge, Button, Field, Input, QueryStates, Textarea } from "@/ui";
import {
  BuilderLayout,
  BuilderSectionCard,
  type BuilderSection,
} from "@/ui/builder/builder-layout";
import { PublishGates } from "@/ui/builder/agent-tests";
import {
  HandlerScope,
  RuntimeControls,
  SupervisedScope,
} from "@/ui/builder/supervisor-scopes";
import { PersonSelect } from "@/ui/builder/person-select";
import {
  Escalations,
  isComplete,
  Notifications,
  QualityGates,
} from "@/ui/builder/supervisor-policy";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * Supervisor — `PLAN.md` §10, on the shared Builder frame.
 *
 * **The two scopes never share a control.** §10 makes them independent, and the surest way to
 * keep that true on a screen is for there to be no widget that could add somebody to both. They
 * also save through different calls behind different permissions, so `my_actions` from the server
 * decides what is offered — the screen never works that out for itself.
 *
 * **What cannot act yet says so.** Monitoring, pause, resume and safe retry are §10 capabilities
 * that need the runtime, which is Gate 7. They are rendered disabled and labelled rather than
 * hidden: hidden would read as "you do not have access", which is a different and untrue
 * statement.
 */
export default function SupervisorFormPage() {
  const t = useTranslations("supervisor");
  const params = useParams<{ id: string }>();
  const id = params.id;

  const supervisor = useQuery({
    queryKey: ["supervisor", id],
    queryFn: ({ signal }) => fetchSupervisor(id, signal),
  });
  const lists = useQuery({
    queryKey: ["supervisor", "lists"],
    queryFn: ({ signal }) => fetchSupervisorLists(signal),
    staleTime: 60 * 60 * 1000,
  });
  //  Who may be named as approver. Inside the same states as the other two, so a failed lookup
  //  reads as a failure rather than as a workspace with nobody in it.
  const people = useQuery({
    queryKey: ["objective", "people"],
    queryFn: ({ signal }) => fetchPeople(signal),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <AppShell
      //  **The top bar names the room, the builder's own heading names the record.** Putting
      //  the record's name here as well printed it twice within an inch of itself — the
      //  duplication complaint. The crumb is the way back to the list and is deliberately
      //  worded differently from the screen name, so it is a link rather than an echo.
      title={t("builderTitle")}
      breadcrumb={[{ label: t("backToList"), href: "/supervisor" }]}
    >
      <QueryStates
        isPending={supervisor.isPending || lists.isPending || people.isPending}
        error={supervisor.error ?? lists.error ?? people.error}
        onRetry={() => void supervisor.refetch()}
      >
        {supervisor.data && lists.data && people.data ? (
          <Editor
            initial={supervisor.data}
            lists={lists.data}
            people={people.data}
            onReload={() => void supervisor.refetch()}
          />
        ) : null}
      </QueryStates>
    </AppShell>
  );
}

type SectionId =
  | "identity"
  | "scopes"
  | "policy"
  | "policy-lists"
  | "limits"
  | "publish";

function Editor({
  initial,
  lists,
  people,
  onReload,
}: {
  initial: Supervisor;
  lists: SupervisorVocabulary;
  people: PersonRef[];
  onReload: () => void;
}) {
  const t = useTranslations("supervisor");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useSession();
  const format = contextFor(user?.timezone);

  const [draft, setDraft] = useState<Supervisor>(initial);
  const [active, setActive] = useState<SectionId>("identity");
  const editable = draft.is_editable && draft.my_actions.includes("edit_draft");
  //  From the server, not derived. A screen deciding for itself which role may do what would be a
  //  second copy of `roles.py`, and the copy on screen is the one people would trust.
  const mayManageHandlers = draft.my_actions.includes("manage_access");

  /*  The version the server last confirmed, in a ref rather than read off the queued draft.

      `autosave.schedule(next)` snapshots the form as it was when somebody typed. If a save is
      already in flight, that snapshot carries the version from *before* it — spent by the time it
      is sent, so the server refuses it and the screen says *"Somebody else saved this"* about a
      person who does not exist. `expected_version` guards against somebody else's write, not
      against this client's own queued edit, so the right value is the newest version this client
      has been given. */
  const confirmedVersion = useRef(draft.version);

  const send = useCallback(
    async (next: Supervisor) => {
      const payload: SupervisorUpdate = {
        name: next.name,
        purpose: next.purpose,
        trigger: next.trigger,
        routing_policy: next.routing_policy,
        max_concurrency: next.max_concurrency,
        cost_cap_minor_units: next.cost_cap_minor_units,
        cost_cap_currency: next.cost_cap_currency,
        token_cap: next.token_cap,
        sla_minutes: next.sla_minutes,
        deadline_minutes: next.deadline_minutes,
        max_retries: next.max_retries,
        retry_backoff_seconds: next.retry_backoff_seconds,
        approver_membership_id: next.approver_membership_id,
        approver_label: next.approver_label,
        escalation_label: next.escalation_label,
        supervised: next.supervised.map((row, index) => ({
          position: index + 1,
          membership_id: row.membership_id,
          agent_id: row.agent_id,
          agent_version_id: row.agent_version_id,
        })),
        /*  These three were mapped from arrays the screen had no way to fill, so they went out
            empty on every save and two publish warnings could never be cleared.

            A row still being typed is held back rather than sent: all three lists have required
            fields, and the escalation's addressee is a check constraint — so an empty new row
            would be refused, and refused while somebody was mid-sentence. It stays on screen and
            says it is not saved yet, which is neither losing it nor claiming it is stored. */
        quality_gates: next.quality_gates
          .filter(isComplete.gate)
          .map(({ id: _id, ...rest }, index) => ({ ...rest, position: index + 1 })),
        escalations: next.escalations
          .filter(isComplete.escalation)
          .map(({ id: _id, escalate_to_name: _n, ...rest }, index) => ({
            ...rest,
            position: index + 1,
          })),
        notifications: next.notifications
          .filter(isComplete.notification)
          .map(({ id: _id, recipient_name: _n, ...rest }, index) => ({
            ...rest,
            position: index + 1,
          })),
        expected_version: confirmedVersion.current,
      };
      const saved = await saveSupervisor(next.id, payload);
      confirmedVersion.current = saved.version;
      //  The server's copy, plus whatever was typed after the payload went out. Taking it
      //  wholesale — which is what this did — discarded those keystrokes.
      setDraft((current) => ({ ...saved, ...unsavedSince(current, next) }));
      //  Saving clears every simulation result, so the panel showing them has to be refetched
      //  rather than left displaying passes that no longer apply.
      void queryClient.invalidateQueries({ queryKey: ["supervisor-sim", next.id] });
      void queryClient.invalidateQueries({ queryKey: ["supervisor-publish", next.id] });
    },
    [queryClient],
  );

  const autosave = useAutosave<Supervisor>(send, { enabled: editable });

  /*  The form follows the server: it takes a fresher copy whenever one arrives and nothing is
      queued, and `resolveConflict` is the way out of a real conflict. See the hook — the reasoning
      is the same on all four Builders, which is why it is one hook. */
  const { resolveConflict } = useAdoptServerVersion<Supervisor>({
    server: initial,
    confirmedVersionRef: confirmedVersion,
    setDraft,
    autosave,
    reload: onReload,
  });


  const edit = useCallback(
    (patch: Partial<Supervisor>) => {
      setDraft((current) => {
        const next = { ...current, ...patch };
        autosave.schedule(next);
        return next;
      });
    },
    [autosave],
  );

  const sections: BuilderSection[] = useMemo(
    () => [
      {
        id: "identity",
        label: t("sections.identity"),
        complete: Boolean(draft.name && draft.purpose),
      },
      {
        id: "scopes",
        label: t("sections.scopes"),
        complete: draft.supervised.length > 0,
        attention: draft.supervised.length === 0,
      },
      {
        id: "policy",
        label: t("sections.policy"),
        complete: draft.escalations.length > 0,
      },
      { id: "limits", label: t("sections.limits") },
      { id: "publish", label: t("sections.publish") },
    ],
    [draft, t],
  );

  function goTo(id: string) {
    setActive(id as SectionId);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <BuilderLayout
      title={draft.name}
      status={<StatusPill status={draft.status} />}
      meta={
        <>
          <span>{t("kindIs", { kind: t(`kind.${draft.kind}`) })}</span>
          <span aria-hidden>·</span>
          {/*  §10's first group is *"Identity, owner, department and linked Objective scope"*, and
              for a department Supervisor the department is the fact that defines what it watches.
              `org_node_name` was on the read schema and shown nowhere. */}
          {draft.org_node_name ? (
            <>
              <span>{t("departmentIs", { name: draft.org_node_name })}</span>
              <span aria-hidden>·</span>
            </>
          ) : null}
          <span>{t("ownerIs", { name: draft.owner_name ?? tCommon("none") })}</span>
          <span aria-hidden>·</span>
          <span>{t("versionIs", { version: draft.version })}</span>
          <span aria-hidden>·</span>
          <span>{t("updatedOn", { date: formatDate(draft.updated_at, format) })}</span>
          {draft.my_role ? (
            <>
              <span aria-hidden>·</span>
              <span>{t("yourRoleIs", { role: t(`role.${draft.my_role}`) })}</span>
            </>
          ) : null}
        </>
      }
      saveState={autosave.state}
      sections={sections}
      activeSection={active}
      onSelectSection={goTo}
      footer={
        <>
          <Button
            variant="secondary"
            icon={<Save className="size-4" />}
            disabled={!editable}
            busy={autosave.state.kind === "saving"}
            onClick={() => void autosave.saveNow(draft)}
          >
            {t("saveDraft")}
          </Button>
          <Button
            variant="primary"
            icon={<Send className="size-4" />}
            onClick={() => goTo("publish")}
          >
            {t("reviewAndPublish")}
          </Button>
          <Button
            variant="ghost"
            className="ml-auto"
            onClick={() => router.push("/supervisor")}
          >
            {tCommon("close")}
          </Button>
        </>
      }
    >
      {autosave.conflicted ? (
        <Alert tone="danger" title={t("conflictTitle")}>
          {t("conflictBody")}{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={resolveConflict}
          >
            {t("keepMyChange")}
          </button>
        </Alert>
      ) : null}

      {autosave.state.kind === "failed" && !autosave.conflicted ? (
        <Alert tone="danger" title={t("notSavedTitle")}>
          {autosave.state.message} {t("notSavedBody")}
        </Alert>
      ) : null}

      {!draft.is_editable ? (
        <Alert tone="info" title={t("readOnlyTitle")}>
          {t("readOnlyBody", { status: t(`status.${draft.status}`) })}
        </Alert>
      ) : !editable ? (
        /*  Editable as a record, but not by this person. A different sentence, because the first
            would be untrue and silence would be worse than both. */
        <Alert tone="info" title={t("notYoursTitle")}>
          {t("notYoursBody", {
            role: draft.my_role ? t(`role.${draft.my_role}`) : t("role.none"),
          })}
        </Alert>
      ) : null}

      <BuilderSectionCard id="identity" title={t("sections.identity")}>
        <div className="space-y-4">
          <Field label={t("field.name")} htmlFor="supervisor-name" required>
            {(field) => (
              <Input
                {...field}
                value={draft.name}
                disabled={!editable}
                onChange={(event) => edit({ name: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("field.purpose")} hint={t("purposeHint")}>
            {(field) => (
              <Textarea
                {...field}
                rows={2}
                value={draft.purpose ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ purpose: event.target.value || null })}
              />
            )}
          </Field>
          <RuntimeControls />
        </div>
      </BuilderSectionCard>

      {/*  §10's two scopes, side by side and sharing no control. */}
      <BuilderSectionCard
        id="scopes"
        title={t("sections.scopes")}
        description={t("scopesDescription")}
      >
        <ScopesSection
          draft={draft}
          lists={lists}
          editable={editable}
          mayManageHandlers={mayManageHandlers}
          onEdit={edit}
          onReload={onReload}
        />
      </BuilderSectionCard>

      <BuilderSectionCard
        id="policy"
        title={t("sections.policy")}
        description={t("policyDescription")}
      >
        <div className="space-y-4">
          <Field label={t("field.routingPolicy")} hint={t("routingHint")}>
            {(field) => (
              <Textarea
                {...field}
                rows={2}
                value={draft.routing_policy ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ routing_policy: event.target.value || null })}
              />
            )}
          </Field>
          {/*  The person, and then the role beside it.

              `submit()` refuses without this id, and until now nothing on the screen could set
              it — so Send for approval was enabled for a call that could only fail, and Approve
              and publish, which compares this against the signed-in person, could never appear at
              all. The free-text label below is the note the workbook asked for, not the
              approver. */}
          <PersonSelect
            label={t("approver")}
            hint={t("approverPerson")}
            required
            value={draft.approver_membership_id ?? null}
            people={people}
            disabled={!editable}
            onChange={(value) => edit({ approver_membership_id: value })}
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("field.approver")} hint={t("approverHint")}>
              {(field) => (
                <Input
                  {...field}
                  value={draft.approver_label ?? ""}
                  disabled={!editable}
                  onChange={(event) =>
                    edit({ approver_label: event.target.value || null })
                  }
                />
              )}
            </Field>
            <Field label={t("field.escalationTo")}>
              {(field) => (
                <Input
                  {...field}
                  value={draft.escalation_label ?? ""}
                  disabled={!editable}
                  onChange={(event) =>
                    edit({ escalation_label: event.target.value || null })
                  }
                />
              )}
            </Field>
          </div>
        </div>
      </BuilderSectionCard>

      {/*  §10 groups 6, 8 and 9. One card, because they are the same question asked three ways:
          what must hold, who to tell when it does not, and who hears about it either way. */}
      <BuilderSectionCard
        id="policy-lists"
        title={t("sections.policyLists")}
        description={t("policyListsDescription")}
      >
        <div className="space-y-6">
          <QualityGates
            rows={draft.quality_gates}
            onFailureOptions={lists.on_failure}
            disabled={!editable}
            onChange={(rows) =>
              edit({ quality_gates: rows as Supervisor["quality_gates"] })
            }
          />
          <Escalations
            rows={draft.escalations}
            people={people}
            disabled={!editable}
            onChange={(rows) => edit({ escalations: rows as Supervisor["escalations"] })}
          />
          <Notifications
            rows={draft.notifications}
            people={people}
            disabled={!editable}
            onChange={(rows) =>
              edit({ notifications: rows as Supervisor["notifications"] })
            }
          />
        </div>
      </BuilderSectionCard>

      <BuilderSectionCard
        id="limits"
        title={t("sections.limits")}
        description={t("limitsDescription")}
      >
        <fieldset disabled={!editable} className="grid gap-4 sm:grid-cols-3">
          {(
            [
              ["max_concurrency", t("field.concurrency"), 1],
              ["token_cap", t("field.tokenCap"), 1],
              ["sla_minutes", t("field.sla"), 1],
              ["deadline_minutes", t("field.deadline"), 1],
              ["max_retries", t("field.retries"), 0],
              ["retry_backoff_seconds", t("field.backoff"), 0],
              //  §10 group 7 is *"Budget, SLA and retry limits"*. The budget half was read on load
              //  and echoed on save with nothing to set it — a value that could round-trip and
              //  never be entered.
              ["cost_cap_minor_units", t("field.costCap"), 0],
            ] as const
          ).map(([key, label, min]) => (
            <Field key={key} label={label}>
              {(field) => (
                <Input
                  {...field}
                  type="number"
                  min={min}
                  value={draft[key] ?? ""}
                  onChange={(event) =>
                    edit({
                      [key]: event.target.value ? Number(event.target.value) : null,
                    } as Partial<Supervisor>)
                  }
                />
              )}
            </Field>
          ))}
        </fieldset>
        <div className="mt-4 max-w-48">
          <Field label={t("field.costCurrency")} hint={t("costCurrencyHint")}>
            {(field) => (
              <Input
                {...field}
                value={draft.cost_cap_currency ?? ""}
                disabled={!editable}
                maxLength={3}
                placeholder="INR"
                onChange={(event) =>
                  edit({
                    cost_cap_currency: event.target.value.toUpperCase() || null,
                  })
                }
              />
            )}
          </Field>
        </div>
      </BuilderSectionCard>

      <BuilderSectionCard id="publish" title={t("sections.publish")}>
        <PublishSection draft={draft} onReload={onReload} />
      </BuilderSectionCard>
    </BuilderLayout>
  );
}

// ---------------------------------------------------------------------------- the two scopes

function ScopesSection({
  draft,
  lists,
  editable,
  mayManageHandlers,
  onEdit,
  onReload,
}: {
  draft: Supervisor;
  lists: SupervisorVocabulary;
  editable: boolean;
  mayManageHandlers: boolean;
  onEdit: (patch: Partial<Supervisor>) => void;
  onReload: () => void;
}) {
  const t = useTranslations("supervisor");
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = () => {
    setBusy(null);
    void queryClient.invalidateQueries({ queryKey: ["supervisor", draft.id] });
    onReload();
  };

  const grant = useMutation({
    mutationFn: ({ membershipId, role }: { membershipId: string; role: string }) =>
      setHandler(draft.id, membershipId, role, draft.version),
    onSettled: refresh,
  });
  const revoke = useMutation({
    mutationFn: (membershipId: string) =>
      removeHandler(draft.id, membershipId, draft.version),
    onSettled: refresh,
  });

  const failed = [grant, revoke].find((mutation) => mutation.isError);

  return (
    <div className="space-y-8">
      {/*  A failed request renders as a failure. Never a toast claiming it worked. */}
      {failed ? (
        <Alert tone="danger">
          {failed.error instanceof Error ? failed.error.message : t("actionFailed")}
        </Alert>
      ) : null}

      <SupervisedScope
        rows={draft.supervised}
        disabled={!editable}
        onChange={(rows) =>
          onEdit({
            /*  Matched on who the row is about, never on where it sits.

                The server-resolved name and row id were looked up by index, into an array the edit
                had already changed. Remove the first of three and the two survivors were
                re-labelled with the removed person's name and given the wrong ids — until a save
                round-tripped, and permanently if that save failed. On the one thing this section
                exists to state. */
            supervised: rows.map((row, index) => {
              const known = draft.supervised.find(
                (existing) =>
                  existing.membership_id === row.membership_id &&
                  (existing.agent_id ?? null) === (row.agent_id ?? null),
              );
              return {
                id: known?.id ?? `pending-${index}`,
                position: row.position,
                membership_id: row.membership_id,
                person_name: known?.person_name ?? null,
                agent_id: row.agent_id ?? null,
                agent_name: known?.agent_name ?? null,
                agent_version_id: row.agent_version_id ?? null,
              };
            }),
          })
        }
      />

      <HandlerScope
        rows={draft.handlers}
        roles={lists.handler_roles}
        mayManage={mayManageHandlers}
        ownerName={draft.owner_name}
        busy={busy}
        onSet={(membershipId, role) => {
          setBusy(membershipId);
          grant.mutate({ membershipId, role });
        }}
        onRemove={(membershipId) => {
          setBusy(membershipId);
          revoke.mutate(membershipId);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------- publish

function PublishSection({
  draft,
  onReload,
}: {
  draft: Supervisor;
  onReload: () => void;
}) {
  const t = useTranslations("supervisor");
  const queryClient = useQueryClient();

  const simulations = useQuery({
    queryKey: ["supervisor-sim", draft.id],
    queryFn: ({ signal }) => fetchSimulations(draft.id, signal),
  });
  const summary = useQuery({
    queryKey: ["supervisor-publish", draft.id],
    queryFn: ({ signal }) => fetchSupervisorPublishSummary(draft.id, signal),
  });
  const versions = useQuery({
    queryKey: ["supervisor-versions", draft.id],
    queryFn: ({ signal }) => fetchSupervisorVersions(draft.id, signal),
  });

  const refresh = () => {
    for (const key of ["supervisor", "supervisor-sim", "supervisor-publish", "supervisor-versions"]) {
      void queryClient.invalidateQueries({ queryKey: [key, draft.id] });
    }
    onReload();
  };

  const record = useMutation({
    mutationFn: (next: SimulationInput[]) =>
      saveSimulations(draft.id, next, draft.version),
    onSuccess: refresh,
  });
  const submit = useMutation({
    mutationFn: () => submitSupervisor(draft.id, draft.version),
    onSuccess: refresh,
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawSupervisor(draft.id, draft.version),
    onSuccess: refresh,
  });
  const approve = useMutation({
    mutationFn: () => publishSupervisor(draft.id, draft.version),
    onSuccess: refresh,
  });

  const failed = [record, submit, withdraw, approve].find((m) => m.isError);

  return (
    <div className="space-y-6">
      {failed ? (
        <Alert tone="danger">
          {failed.error instanceof Error ? failed.error.message : t("actionFailed")}
        </Alert>
      ) : null}

      <QueryStates
        isPending={simulations.isPending}
        error={simulations.error}
        onRetry={() => void simulations.refetch()}
      >
        {simulations.data ? (
          <Simulations
            rows={simulations.data.simulations ?? []}
            passed={simulations.data.passed}
            total={simulations.data.total}
            disabled={!draft.is_editable || !draft.my_actions.includes("edit_draft")}
            saving={record.isPending}
            onSave={(next) => record.mutate(next)}
          />
        ) : null}
      </QueryStates>

      <QueryStates
        isPending={summary.isPending}
        error={summary.error}
        onRetry={() => void summary.refetch()}
      >
        {summary.data ? (
          <>
            <PublishGates
              gates={summary.data.gates}
              warnings={summary.data.warnings}
              nextAction={summary.data.next_action}
            />

            <div className="flex flex-wrap gap-2 border-t border-border pt-4">
              {summary.data.can_submit ? (
                <Button
                  variant="primary"
                  icon={<Send className="size-4" />}
                  busy={submit.isPending}
                  disabled={!summary.data.gates.every((gate) => gate.passed)}
                  onClick={() => submit.mutate()}
                >
                  {t("submitForApproval")}
                </Button>
              ) : null}

              {draft.status === "ready_to_publish" ? (
                <Button
                  variant="secondary"
                  icon={<Undo2 className="size-4" />}
                  busy={withdraw.isPending}
                  onClick={() => withdraw.mutate()}
                >
                  {t("withdraw")}
                </Button>
              ) : null}

              {summary.data.can_approve ? (
                <Button
                  variant="primary"
                  icon={<CheckCircle2 className="size-4" />}
                  busy={approve.isPending}
                  onClick={() => approve.mutate()}
                >
                  {t("approveAndPublish")}
                </Button>
              ) : null}
            </div>
          </>
        ) : null}
      </QueryStates>

      {versions.data && !versions.data.is_empty ? (
        <section aria-labelledby="versions" className="space-y-2 border-t border-border pt-4">
          <h3 id="versions" className="text-sm font-semibold">
            {t("versionsTitle")}
          </h3>
          <ul className="space-y-1.5 text-sm">
            {(versions.data.versions ?? []).map((version) => (
              <li key={version.id} className="flex flex-wrap items-center gap-2">
                <Badge tone="success">v{version.version_no}</Badge>
                <span>{version.name}</span>
                {version.approved_by_name ? (
                  <span className="text-xs text-muted-foreground">
                    {t("approvedBy", { name: version.approved_by_name })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Simulations({
  rows,
  passed,
  total,
  disabled,
  saving,
  onSave,
}: {
  rows: { name: string; what_fails: string; expected_response: string; status: string; observed: string | null }[];
  passed: number;
  total: number;
  disabled: boolean;
  saving: boolean;
  onSave: (next: SimulationInput[]) => void;
}) {
  const t = useTranslations("supervisor");
  const [draft, setDraft] = useState<SimulationInput[]>(
    rows.map((row) => ({
      name: row.name,
      what_fails: row.what_fails,
      expected_response: row.expected_response,
      status: row.status as SimulationInput["status"],
      observed: row.observed,
    })),
  );

  const set = (index: number, patch: Partial<SimulationInput>) =>
    setDraft((current) =>
      current.map((row, at) => (at === index ? { ...row, ...patch } : row)),
    );

  const add = () =>
    setDraft((current) => [
      ...current,
      { name: "", what_fails: "", expected_response: "", status: "not_run", observed: null },
    ]);

  const complete = draft.every(
    (row) => row.name.trim() && row.what_fails.trim() && row.expected_response.trim(),
  );

  return (
    <div className="space-y-3">
      <Alert tone={total > 0 && passed === total ? "success" : "info"}>
        {total === 0
          ? t("noScenariosYet")
          : t("simulationsProgress", { passed, total })}
      </Alert>
      <p className="text-sm text-muted-foreground">{t("simulationsIntro")}</p>

      <ul className="space-y-3">
        {draft.map((row, index) => {
          //  The schema refuses a result with no observation, so the control that would produce
          //  one is disabled and labelled rather than left to fail at the database.
          const observed = Boolean(row.observed?.trim());
          return (
            <li key={index} className="space-y-3 rounded-lg border border-border bg-card p-3">
              <Field label={t("field.scenarioName")}>
                {(field) => (
                  <Input
                    {...field}
                    value={row.name}
                    disabled={disabled}
                    onChange={(event) => set(index, { name: event.target.value })}
                  />
                )}
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={t("field.whatFails")}>
                  {(field) => (
                    <Textarea
                      {...field}
                      rows={2}
                      value={row.what_fails}
                      disabled={disabled}
                      onChange={(event) => set(index, { what_fails: event.target.value })}
                    />
                  )}
                </Field>
                <Field label={t("field.expectedResponse")}>
                  {(field) => (
                    <Textarea
                      {...field}
                      rows={2}
                      value={row.expected_response}
                      disabled={disabled}
                      onChange={(event) =>
                        set(index, { expected_response: event.target.value })
                      }
                    />
                  )}
                </Field>
              </div>
              <Field label={t("field.observed")} hint={t("observedHint")}>
                {(field) => (
                  <Textarea
                    {...field}
                    rows={2}
                    value={row.observed ?? ""}
                    disabled={disabled}
                    onChange={(event) =>
                      set(index, { observed: event.target.value || null })
                    }
                  />
                )}
              </Field>
              <div className="flex flex-wrap items-center gap-1.5">
                {(["not_run", "pass", "fail", "blocked"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={row.status === option}
                    disabled={disabled || (option !== "not_run" && !observed)}
                    onClick={() => set(index, { status: option })}
                    className={
                      row.status === option
                        ? "rounded-full border border-[var(--ub-brand)] bg-primary px-3 py-1 text-xs text-primary-foreground"
                        : "rounded-full border border-border bg-card px-3 py-1 text-xs hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                    }
                  >
                    {t(`simulationStatus.${option}`)}
                  </button>
                ))}
                {!observed ? (
                  <span className="text-xs text-muted-foreground">
                    {t("needsObservation")}
                  </span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>

      {!disabled ? (
        <div className="flex gap-2">
          <Button variant="secondary" onClick={add}>
            {t("addScenario")}
          </Button>
          <Button
            variant="primary"
            busy={saving}
            disabled={draft.length === 0 || !complete}
            onClick={() => onSave(draft)}
          >
            {t("saveScenarios")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const t = useTranslations("supervisor");
  const tones: Record<string, "neutral" | "human" | "approval" | "success"> = {
    draft: "neutral",
    needs_review: "approval",
    ready_to_publish: "human",
    published: "success",
    active: "success",
    paused: "approval",
    archived: "neutral",
  };
  return <Badge tone={tones[status] ?? "neutral"}>{t(`status.${status}`)}</Badge>;
}
