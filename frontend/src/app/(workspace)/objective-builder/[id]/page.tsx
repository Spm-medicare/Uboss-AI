"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus, Save, Send, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import type { CurrentStepInput, ObjectiveUpdate } from "@/lib/api/contract";
import {
  fetchObjective,
  fetchPeople,
  fetchWorkbookLists,
  saveObjective,
  type Lists,
  type Objective,
} from "@/lib/api/objectives";
import { useAutosave } from "@/lib/builder/use-autosave";
import { contextFor, formatDate } from "@/lib/format";
import { useSession } from "@/lib/auth/use-session";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Field,
  Input,
  QueryStates,
  Textarea,
} from "@/ui";
import {
  BuilderLayout,
  BuilderSectionCard,
  type BuilderSection,
} from "@/ui/builder/builder-layout";
import { PlanSection } from "@/ui/builder/plan-section";
import { PublishSection } from "@/ui/builder/publish-section";
import { StepCard } from "@/ui/builder/step-card";
import { Suggest } from "@/ui/builder/suggest";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * Objective Agent Builder — the form.
 *
 * PLAN §7 says this module holds *"all Objective cards, creation, analysis, publishing and
 * progress. There is no duplicate Objective page."* So the list and the form are one screen's
 * worth of the same module, and the Objective entry in the sidebar deliberately does not exist.
 *
 * The field set comes from two places and `docs/architecture/OBJECTIVE_FIELDS.md` says why. The
 * *Current process* section is the approved workbook's fourteen columns, unchanged; the rest is
 * §7's groups. Nothing from the workbook was dropped to make the form shorter.
 *
 * **The form holds the draft; the server holds the truth.** Every edit updates local state and
 * queues an autosave. A save returns the whole objective and replaces the local copy, so the two
 * cannot drift after a save that changed something the client did not send — a version number,
 * for instance, which every subsequent save depends on.
 */
export default function ObjectiveBuilderPage() {
  const t = useTranslations("objective");
  const params = useParams<{ id: string }>();
  const id = params.id;

  const objective = useQuery({
    queryKey: ["objective", id],
    queryFn: ({ signal }) => fetchObjective(id, signal),
  });
  const lists = useQuery({
    queryKey: ["objective", "lists"],
    queryFn: ({ signal }) => fetchWorkbookLists(signal),
    staleTime: 60 * 60 * 1000,
  });
  const people = useQuery({
    queryKey: ["objective", "people"],
    queryFn: ({ signal }) => fetchPeople(signal),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <AppShell
      title={t("builderTitle")}
      breadcrumb={[{ label: t("objectives"), href: "/objective-builder" }]}
    >
      <QueryStates
        isPending={objective.isPending || lists.isPending}
        error={objective.error ?? lists.error}
        onRetry={() => void objective.refetch()}
      >
        {objective.data && lists.data ? (
          <Editor
            initial={objective.data}
            lists={lists.data}
            people={people.data ?? []}
            onReload={() => void objective.refetch()}
          />
        ) : null}
      </QueryStates>
    </AppShell>
  );
}

/** The eight sections, in the order the form presents them. */
type SectionId =
  | "identity"
  | "process"
  | "outcome"
  | "scope"
  | "time"
  | "constraints"
  | "governance"
  | "ai"
  | "plan"
  | "publish";

function Editor({
  initial,
  lists,
  people,
  onReload,
}: {
  initial: Objective;
  lists: Lists;
  people: Awaited<ReturnType<typeof fetchPeople>>;
  onReload: () => void;
}) {
  const t = useTranslations("objective");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const { user } = useSession();
  const format = contextFor(user?.timezone);

  const [draft, setDraft] = useState<Objective>(initial);
  const [active, setActive] = useState<SectionId>("identity");
  const editable = draft.is_editable;

  const send = useCallback(
    async (next: Objective) => {
      const payload: ObjectiveUpdate = {
        title: next.title,
        department: next.department,
        owner_membership_id: next.owner_membership_id,
        expected_result: next.expected_result,
        workload_count: next.workload_count,
        workload_unit: next.workload_unit,
        target_date: next.target_date,
        description: next.description,
        priority: next.priority,
        baseline: next.baseline,
        success_measures: next.success_measures,
        included_work: next.included_work,
        excluded_work: next.excluded_work,
        stakeholders: next.stakeholders,
        geography: next.geography,
        start_date: next.start_date,
        urgency: next.urgency,
        budget_note: next.budget_note,
        policy_constraints: next.policy_constraints,
        dependencies: next.dependencies,
        risk_note: next.risk_note,
        approver_membership_id: next.approver_membership_id,
        visibility: next.visibility,
        handles_sensitive_data: next.handles_sensitive_data,
        sensitive_data_note: next.sensitive_data_note,
        ai_assistance: next.ai_assistance,
        human_checkpoints: next.human_checkpoints,
        current_steps: (next.current_steps ?? []).map(stripReadFields),
        expected_version: next.version,
      };
      const saved = await saveObjective(next.id, payload);
      //  The server's copy replaces the local one — it carries the new version number, and every
      //  subsequent save depends on it. Keeping the local copy would make the second save a
      //  guaranteed conflict.
      setDraft((current) => ({ ...saved, ...unsavedSince(current, next) }));
    },
    [],
  );

  const autosave = useAutosave<Objective>(send, { enabled: editable });

  const edit = useCallback(
    (patch: Partial<Objective>) => {
      setDraft((current) => {
        const next = { ...current, ...patch };
        autosave.schedule(next);
        return next;
      });
    },
    [autosave],
  );

  const steps = draft.current_steps;

  const setSteps = useCallback(
    (next: CurrentStepInput[]) => {
      edit({ current_steps: next as Objective["current_steps"] });
    },
    [edit],
  );

  const sections: BuilderSection[] = useMemo(
    () => [
      {
        id: "identity",
        label: t("sections.identity"),
        complete: Boolean(draft.title && draft.department && draft.expected_result),
      },
      {
        id: "process",
        label: t("sections.process"),
        complete: steps.length > 0,
        attention: steps.length === 0,
      },
      { id: "outcome", label: t("sections.outcome"), complete: Boolean(draft.success_measures) },
      { id: "scope", label: t("sections.scope"), complete: Boolean(draft.included_work) },
      { id: "time", label: t("sections.time"), complete: Boolean(draft.target_date) },
      {
        id: "constraints",
        label: t("sections.constraints"),
        complete: Boolean(draft.risk_note || draft.policy_constraints),
      },
      {
        id: "governance",
        label: t("sections.governance"),
        complete: Boolean(draft.approver_membership_id),
      },
      { id: "ai", label: t("sections.ai"), complete: true },
      { id: "plan", label: t("sections.plan"), complete: false },
      { id: "publish", label: t("sections.publish") },
    ],
    [draft, steps.length, t],
  );

  function goTo(id: string) {
    setActive(id as SectionId);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <BuilderLayout
      eyebrow={t("eyebrow")}
      title={draft.title}
      status={<StatusPill status={draft.status} />}
      meta={
        <>
          <span>{t("ownerIs", { name: draft.owner_name ?? tCommon("none") })}</span>
          <span aria-hidden>·</span>
          <span>{t("versionIs", { version: draft.version })}</span>
          <span aria-hidden>·</span>
          <span>{t("updatedOn", { date: formatDate(draft.updated_at, format) })}</span>
        </>
      }
      saveState={autosave.state}
      sections={sections}
      activeSection={active}
      onSelectSection={goTo}
      aside={
        <Guidance
          steps={steps.length}
          hasResult={Boolean(draft.expected_result)}
          hasApprover={Boolean(draft.approver_membership_id)}
        />
      }
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
            icon={<Sparkles className="size-4" />}
            disabled={!editable || steps.length === 0}
            title={steps.length === 0 ? t("analyseNeedsSteps") : undefined}
            onClick={() => goTo("plan")}
          >
            {t("analyse")}
          </Button>
          <Button
            variant="primary"
            icon={<Send className="size-4" />}
            onClick={() => goTo("publish")}
          >
            {t("reviewAndPublish")}
          </Button>
          {steps.length === 0 ? (
            <span className="text-xs text-muted-foreground">{t("analyseNeedsSteps")}</span>
          ) : null}
          <Button variant="ghost" className="ml-auto" onClick={() => router.push("/objective-builder")}>
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
            onClick={onReload}
          >
            {t("reloadIt")}
          </button>
        </Alert>
      ) : null}

      {autosave.state.kind === "failed" && !autosave.conflicted ? (
        <Alert tone="danger" title={t("notSavedTitle")}>
          {autosave.state.message} {t("notSavedBody")}
        </Alert>
      ) : null}

      {!editable ? (
        <Alert tone="info" title={t("readOnlyTitle")}>
          {t("readOnlyBody", { status: t(`status.${draft.status}`) })}
        </Alert>
      ) : null}

      {/*  ── 1. Identity — the workbook's heading block ───────────────────────────── */}
      <BuilderSectionCard
        id="identity"
        accent="primary"
        title={t("sections.identity")}
        description={t("identityHelp")}
      >
        <Field label={t("objectiveName")} required>
          {(field) => (
            <Input
              {...field}
              value={draft.title}
              disabled={!editable}
              onChange={(event) => edit({ title: event.target.value })}
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Suggest
            label={`${t("department")} *`}
            value={draft.department ?? ""}
            options={lists.departments}
            disabled={!editable}
            onChange={(value) => edit({ department: value || null })}
          />
          <PersonSelect
            label={`${t("owner")} *`}
            value={draft.owner_membership_id}
            people={people}
            disabled={!editable}
            onChange={(value) => edit({ owner_membership_id: value })}
          />
        </div>

        <Field label={t("expectedResult")} required>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={draft.expected_result ?? ""}
              disabled={!editable}
              onChange={(event) => edit({ expected_result: event.target.value || null })}
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("currentWorkload")}>
            {(field) => (
              <Input
                {...field}
                value={draft.workload_count ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ workload_count: event.target.value || null })}
              />
            )}
          </Field>
          <Suggest
            label={t("unit")}
            value={draft.workload_unit ?? ""}
            options={lists.workload_units}
            disabled={!editable}
            onChange={(value) => edit({ workload_unit: value || null })}
          />
          <Field label={t("targetCompletion")}>
            {(field) => (
              <Input
                {...field}
                type="date"
                value={draft.target_date ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ target_date: event.target.value || null })}
              />
            )}
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Choice
            label={t("priority")}
            value={draft.priority}
            options={["low", "normal", "high", "critical"]}
            render={(value) => t(`priorityValue.${value}`)}
            disabled={!editable}
            onChange={(value) => edit({ priority: value as Objective["priority"] })}
          />
          <Field label={t("preparedBy")}>
            {() => (
              //  Not a box. The signed-in person is who prepared it, and the row already knows —
              //  a field to type somebody else's name into is a field that will be wrong.
              <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-sm">
                {user?.display_name ?? "—"}
              </p>
            )}
          </Field>
        </div>
      </BuilderSectionCard>

      {/*  ── 2. The current process — the workbook's step table ───────────────────── */}
      <BuilderSectionCard
        id="process"
        accent="human"
        title={t("sections.process")}
        description={t("processHelp")}
      >
        {steps.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center">
            <p className="text-sm font-medium">{t("noStepsTitle")}</p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
              {t("noStepsBody")}
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {steps.map((step, index) => (
              <StepCard
                key={index}
                step={step}
                index={index}
                total={steps.length}
                lists={lists}
                disabled={!editable}
                onChange={(next) =>
                  setSteps(steps.map((item, at) => (at === index ? next : item)))
                }
                onRemove={() => setSteps(steps.filter((_, at) => at !== index))}
                onMove={(direction) => {
                  const target = index + direction;
                  if (target < 0 || target >= steps.length) return;
                  const next = [...steps];
                  const moved = next[index]!;
                  next[index] = next[target]!;
                  next[target] = moved;
                  setSteps(next);
                }}
              />
            ))}
          </ul>
        )}

        <Button
          icon={<Plus className="size-4" />}
          disabled={!editable}
          onClick={() => setSteps([...steps, {}])}
        >
          {t("addStep")}
        </Button>
      </BuilderSectionCard>

      {/*  ── 3. Outcome ──────────────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="outcome"
        accent="success"
        title={t("sections.outcome")}
        description={t("outcomeHelp")}
      >
        <LongField
          label={t("baseline")}
          value={draft.baseline}
          disabled={!editable}
          onChange={(value) => edit({ baseline: value })}
        />
        <LongField
          label={t("successMeasures")}
          value={draft.success_measures}
          disabled={!editable}
          onChange={(value) => edit({ success_measures: value })}
        />
      </BuilderSectionCard>

      {/*  ── 4. Scope ────────────────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="scope"
        accent="hybrid"
        title={t("sections.scope")}
        description={t("scopeHelp")}
      >
        <LongField
          label={t("includedWork")}
          value={draft.included_work}
          disabled={!editable}
          onChange={(value) => edit({ included_work: value })}
        />
        <LongField
          label={t("excludedWork")}
          value={draft.excluded_work}
          disabled={!editable}
          onChange={(value) => edit({ excluded_work: value })}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <ShortField
            label={t("stakeholders")}
            value={draft.stakeholders}
            disabled={!editable}
            onChange={(value) => edit({ stakeholders: value })}
          />
          <ShortField
            label={t("geography")}
            value={draft.geography}
            disabled={!editable}
            onChange={(value) => edit({ geography: value })}
          />
        </div>
      </BuilderSectionCard>

      {/*  ── 5. Time ─────────────────────────────────────────────────────────────── */}
      <BuilderSectionCard id="time" accent="primary" title={t("sections.time")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("startDate")}>
            {(field) => (
              <Input
                {...field}
                type="date"
                value={draft.start_date ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ start_date: event.target.value || null })}
              />
            )}
          </Field>
          <ShortField
            label={t("urgency")}
            value={draft.urgency}
            disabled={!editable}
            onChange={(value) => edit({ urgency: value })}
          />
        </div>
      </BuilderSectionCard>

      {/*  ── 6. Constraints ──────────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="constraints"
        accent="approval"
        title={t("sections.constraints")}
        description={t("constraintsHelp")}
      >
        <LongField
          label={t("budgetNote")}
          value={draft.budget_note}
          disabled={!editable}
          onChange={(value) => edit({ budget_note: value })}
        />
        <LongField
          label={t("policyConstraints")}
          value={draft.policy_constraints}
          disabled={!editable}
          onChange={(value) => edit({ policy_constraints: value })}
        />
        <LongField
          label={t("dependencies")}
          value={draft.dependencies}
          disabled={!editable}
          onChange={(value) => edit({ dependencies: value })}
        />
        <LongField
          label={t("riskNote")}
          value={draft.risk_note}
          disabled={!editable}
          onChange={(value) => edit({ risk_note: value })}
        />
      </BuilderSectionCard>

      {/*  ── 7. Governance ───────────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="governance"
        accent="danger"
        title={t("sections.governance")}
        description={t("governanceHelp")}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <PersonSelect
            label={t("approver")}
            value={draft.approver_membership_id}
            people={people}
            disabled={!editable}
            onChange={(value) => edit({ approver_membership_id: value })}
          />
          <Choice
            label={t("visibility")}
            value={draft.visibility}
            options={["owner", "department", "company"]}
            render={(value) => t(`visibilityValue.${value}`)}
            disabled={!editable}
            onChange={(value) => edit({ visibility: value as Objective["visibility"] })}
          />
        </div>

        {draft.approver_membership_id &&
        draft.approver_membership_id === draft.owner_membership_id ? (
          <Alert tone="warning">{t("selfApprovalWarning")}</Alert>
        ) : null}

        <label className="flex items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={draft.handles_sensitive_data}
            disabled={!editable}
            onChange={(event) => edit({ handles_sensitive_data: event.target.checked })}
            className="mt-0.5 size-4 rounded border-border"
          />
          <span>
            <span className="font-medium">{t("sensitiveData")}</span>
            <span className="block text-muted-foreground">{t("sensitiveDataHelp")}</span>
          </span>
        </label>

        {draft.handles_sensitive_data ? (
          <LongField
            label={t("sensitiveDataNote")}
            value={draft.sensitive_data_note}
            disabled={!editable}
            onChange={(value) => edit({ sensitive_data_note: value })}
          />
        ) : null}
      </BuilderSectionCard>

      {/*  ── 9. The proposed plan ────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="ai"
        accent="ai"
        title={t("sections.ai")}
        description={t("aiHelp")}
      >
        <Choice
          label={t("aiAssistance")}
          value={draft.ai_assistance}
          options={["none", "propose_only", "propose_and_draft"]}
          render={(value) => t(`assistanceValue.${value}`)}
          disabled={!editable}
          onChange={(value) => edit({ ai_assistance: value as Objective["ai_assistance"] })}
        />
        <LongField
          label={t("humanCheckpoints")}
          value={draft.human_checkpoints}
          disabled={!editable}
          onChange={(value) => edit({ human_checkpoints: value })}
        />
      </BuilderSectionCard>

      {/*  ── 9. The plan the analysis proposed ───────────────────────────────────── */}
      <BuilderSectionCard
        id="plan"
        accent="ai"
        title={t("sections.plan")}
        description={t("planHelp")}
      >
        <PlanSection
          objectiveId={draft.id}
          objectiveVersion={draft.version}
          editable={editable}
          timeZone={user?.timezone}
          onReloadObjective={onReload}
        />
      </BuilderSectionCard>

      {/*  ── 10. Publish ─────────────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="publish"
        accent="success"
        title={t("sections.publish")}
        description={t("publishHelp")}
      >
        <PublishSection
          objectiveId={draft.id}
          editable={editable}
          timeZone={user?.timezone}
          onChanged={onReload}
        />
      </BuilderSectionCard>
    </BuilderLayout>
  );
}

/** The read-only fields the API adds. They are not part of what a save sends back. */
function stripReadFields(step: Objective["current_steps"][number]): CurrentStepInput {
  const { id: _id, position: _position, ...rest } = step;
  return rest;
}

/**
 * What the person typed while a save was in flight.
 *
 * A save takes a moment, and somebody keeps typing during it. Without this, the server's reply
 * would overwrite those keystrokes — the classic autosave bug, and the one people notice.
 */
function unsavedSince(
  current: Objective,
  sent: Objective,
): Partial<Objective> {
  const changed: Partial<Objective> = {};
  for (const key of Object.keys(current) as (keyof Objective)[]) {
    if (key === "version" || key === "updated_at" || key === "is_editable") continue;
    if (JSON.stringify(current[key]) !== JSON.stringify(sent[key])) {
      changed[key] = current[key] as never;
    }
  }
  return changed;
}

function StatusPill({ status }: { status: Objective["status"] }) {
  const t = useTranslations("objective");
  const tones: Record<string, "neutral" | "human" | "ai" | "approval" | "success" | "danger"> = {
    draft: "neutral",
    analyzing: "ai",
    needs_review: "approval",
    ready_to_publish: "human",
    published: "success",
    active: "success",
    paused: "approval",
    archived: "neutral",
  };
  return <Badge tone={tones[status] ?? "neutral"}>{t(`status.${status}`)}</Badge>;
}

/**
 * The right column — §29's "contextual help, warnings and summary".
 *
 * Every line here is derived from what is actually in the form. No progress percentage: a
 * percentage needs a definition of "complete", and inventing one would put a number on screen
 * that means nothing.
 */
function Guidance({
  steps,
  hasResult,
  hasApprover,
}: {
  steps: number;
  hasResult: boolean;
  hasApprover: boolean;
}) {
  const t = useTranslations("objective");
  const todo = [
    !hasResult ? t("todoResult") : null,
    steps === 0 ? t("todoSteps") : null,
    !hasApprover ? t("todoApprover") : null,
  ].filter(Boolean) as string[];

  return (
    <Card>
      <CardBody className="space-y-3">
        <p className="text-sm font-semibold">{t("guidanceTitle")}</p>
        <p className="text-sm text-muted-foreground">{t("guidanceBody")}</p>
        {todo.length > 0 ? (
          <>
            <p className="pt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("stillNeeded")}
            </p>
            <ul className="space-y-1.5 text-sm">
              {todo.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <span aria-hidden className="mt-1.5 size-1.5 shrink-0 rounded-full bg-approval" />
                  {item}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="flex items-center gap-2 text-sm text-success">
            <span aria-hidden className="size-1.5 rounded-full bg-success" />
            {t("nothingOutstanding")}
          </p>
        )}
        <p className="border-t border-border pt-3 text-xs text-muted-foreground">
          {t("stepsRecorded", { count: steps })}
        </p>
      </CardBody>
    </Card>
  );
}

function PersonSelect({
  label,
  value,
  people,
  disabled,
  onChange,
}: {
  label: string;
  value: string | null;
  people: { membership_id: string; display_name: string; job_title?: string | null }[];
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations("objective");
  return (
    <Field label={label}>
      {(field) => (
        <select
          {...field}
          value={value ?? ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value || null)}
          className="h-9 w-full rounded-md border border-border bg-card px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
        >
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

/**
 * A small closed set, as buttons rather than a dropdown.
 *
 * Four options are faster to read side by side than behind a click, and the current one is
 * visible without opening anything. Used only where the set really is closed — the workbook's
 * lists are not, and they use `Suggest`.
 */
function Choice({
  label,
  value,
  options,
  render,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  render: (value: string) => string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset disabled={disabled}>
      <legend className="mb-1.5 block text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={value === option}
            onClick={() => onChange(option)}
            className={`rounded-md border px-2.5 py-1.5 text-sm transition-colors duration-150 motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)] disabled:cursor-not-allowed disabled:opacity-60 ${
              value === option
                ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-accent"
            }`}
          >
            {render(option)}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function LongField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string | null;
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  return (
    <Field label={label}>
      {(field) => (
        <Textarea
          {...field}
          rows={2}
          value={value ?? ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value || null)}
        />
      )}
    </Field>
  );
}

function ShortField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string | null;
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  return (
    <Field label={label}>
      {(field) => (
        <Input
          {...field}
          value={value ?? ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value || null)}
        />
      )}
    </Field>
  );
}
