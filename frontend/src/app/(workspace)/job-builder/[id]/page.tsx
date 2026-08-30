"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Save, Send, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import type {
  AssignmentRuleInput,
  JobInputDefinition,
  JobStepInput,
  JobUpdate,
} from "@/lib/api/contract";
import {
  fetchJob,
  fetchJobLists,
  fetchJobPublishSummary,
  fetchJobVersions,
  publishJob,
  saveJob,
  submitJob,
  withdrawJob,
  type Job,
  type Lists,
} from "@/lib/api/jobs";
import { fetchPeople } from "@/lib/api/objectives";
import { useAutosave } from "@/lib/builder/use-autosave";
import { useSession } from "@/lib/auth/use-session";
import { contextFor, formatDate, formatDateTime } from "@/lib/format";
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
import { JobStepCard } from "@/ui/builder/job-step-card";
import { ScheduleSection } from "@/ui/builder/schedule-section";
import { Suggest } from "@/ui/builder/suggest";
import { JobInputs, WhoRules } from "@/ui/builder/who-and-inputs";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * Job Builder — the approved workbook's Form 3 and PLAN §8's ten groups.
 *
 * On the same frame as the Objective Agent Builder, because §6 calls it the *shared* Builder
 * experience: same section rail, same save states, same sticky footer, same autosave rules. A
 * person who has filled in one should not have to learn a second.
 *
 * The order of the sections follows what somebody actually knows when they sit down. The method
 * comes before who does it and what it needs, because a person describing their own work starts
 * by describing the work.
 */
export default function JobBuilderFormPage() {
  const t = useTranslations("job");
  const params = useParams<{ id: string }>();
  const id = params.id;

  const job = useQuery({
    queryKey: ["job", id],
    queryFn: ({ signal }) => fetchJob(id, signal),
  });
  const lists = useQuery({
    queryKey: ["job", "lists"],
    queryFn: ({ signal }) => fetchJobLists(signal),
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
      breadcrumb={[{ label: t("jobs"), href: "/job-builder" }]}
    >
      <QueryStates
        isPending={job.isPending || lists.isPending}
        error={job.error ?? lists.error}
        onRetry={() => void job.refetch()}
      >
        {job.data && lists.data ? (
          <Editor
            initial={job.data}
            lists={lists.data}
            people={people.data ?? []}
            onReload={() => void job.refetch()}
          />
        ) : null}
      </QueryStates>
    </AppShell>
  );
}

type SectionId =
  | "identity"
  | "method"
  | "who"
  | "inputs"
  | "quality"
  | "schedule"
  | "publish";

function Editor({
  initial,
  lists,
  people,
  onReload,
}: {
  initial: Job;
  lists: Lists;
  people: Awaited<ReturnType<typeof fetchPeople>>;
  onReload: () => void;
}) {
  const t = useTranslations("job");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const { user } = useSession();
  const format = contextFor(user?.timezone);

  const [draft, setDraft] = useState<Job>(initial);
  const [active, setActive] = useState<SectionId>("identity");
  const editable = draft.is_editable;

  const send = useCallback(async (next: Job) => {
    const payload: JobUpdate = {
      name: next.name,
      objective_id: next.objective_id,
      department: next.department,
      external_ref: next.external_ref,
      owner_membership_id: next.owner_membership_id,
      current_person: next.current_person,
      current_role: next.current_role,
      trigger: next.trigger,
      frequency: next.frequency,
      high_level_work: next.high_level_work,
      start_requirement: next.start_requirement,
      completion_evidence: next.completion_evidence,
      normal_completion_time: next.normal_completion_time,
      time_unit: next.time_unit,
      purpose: next.purpose,
      expected_output: next.expected_output,
      quality_checks: next.quality_checks,
      sla_note: next.sla_note,
      retry_policy: next.retry_policy,
      failure_action: next.failure_action,
      escalation_to: next.escalation_to,
      visibility: next.visibility,
      approver_membership_id: next.approver_membership_id,
      steps: next.steps.map(stripReadFields),
      assignment_rules: next.assignment_rules.map(({ id: _id, position: _p, ...rest }) => rest),
      inputs: next.inputs.map(({ id: _id, position: _p, ...rest }) => rest),
      expected_version: next.version,
    };
    const saved = await saveJob(next.id, payload);
    //  The server's copy wins, except for anything typed while the request was out — the classic
    //  autosave bug, and the one people notice.
    setDraft((current) => ({ ...saved, ...unsavedSince(current, next) }));
  }, []);

  const autosave = useAutosave<Job>(send, { enabled: editable });

  const edit = useCallback(
    (patch: Partial<Job>) => {
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
        complete: Boolean(draft.name && draft.trigger && draft.high_level_work),
      },
      {
        id: "method",
        label: t("sections.method"),
        complete: draft.steps.length > 0,
        attention: draft.steps.length === 0,
      },
      {
        id: "who",
        label: t("sections.who"),
        complete: draft.assignment_rules.length > 0,
        attention: draft.assignment_rules.length === 0,
      },
      { id: "inputs", label: t("sections.inputs"), complete: draft.inputs.length > 0 },
      {
        id: "quality",
        label: t("sections.quality"),
        complete: Boolean(draft.completion_evidence),
      },
      { id: "schedule", label: t("sections.schedule") },
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
      eyebrow={t("eyebrow")}
      title={draft.name}
      status={<StatusPill status={draft.status} />}
      meta={
        <>
          <span>{t("ownerIs", { name: draft.owner_name ?? tCommon("none") })}</span>
          <span aria-hidden>·</span>
          <span>{t("versionIs", { version: draft.version })}</span>
          <span aria-hidden>·</span>
          <span>{t("updatedOn", { date: formatDate(draft.updated_at, format) })}</span>
          {draft.objective_name ? (
            <>
              <span aria-hidden>·</span>
              <span>{t("forObjective", { name: draft.objective_name })}</span>
            </>
          ) : null}
        </>
      }
      saveState={autosave.state}
      sections={sections}
      activeSection={active}
      onSelectSection={goTo}
      aside={<Guidance draft={draft} />}
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
            onClick={() => router.push("/job-builder")}
          >
            {tCommon("close")}
          </Button>
        </>
      }
    >
      {autosave.conflicted ? (
        <Alert tone="danger" title={t("conflictTitle")}>
          {t("conflictBody")}{" "}
          <button type="button" className="underline underline-offset-4" onClick={onReload}>
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

      {/*  ── 1. Identity — Form 3's heading block ────────────────────────────────── */}
      <BuilderSectionCard
        id="identity"
        accent="primary"
        title={t("sections.identity")}
        description={t("identityHelp")}
      >
        <Field label={t("jobName")} required>
          {(field) => (
            <Input
              {...field}
              value={draft.name}
              disabled={!editable}
              onChange={(event) => edit({ name: event.target.value })}
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Suggest
            label={t("department")}
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

        <div className="grid gap-4 sm:grid-cols-2">
          <Suggest
            label={t("currentPerson")}
            value={draft.current_person ?? ""}
            disabled={!editable}
            onChange={(value) => edit({ current_person: value || null })}
          />
          <Suggest
            label={t("currentRole")}
            value={draft.current_role ?? ""}
            disabled={!editable}
            onChange={(value) => edit({ current_role: value || null })}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Suggest
            label={`${t("trigger")} *`}
            value={draft.trigger ?? ""}
            options={lists.triggers}
            disabled={!editable}
            onChange={(value) => edit({ trigger: value || null })}
          />
          <Suggest
            label={`${t("frequency")} *`}
            value={draft.frequency ?? ""}
            options={lists.frequencies}
            disabled={!editable}
            onChange={(value) => edit({ frequency: value || null })}
          />
        </div>

        <LongField
          label={`${t("highLevelWork")} *`}
          value={draft.high_level_work}
          disabled={!editable}
          onChange={(value) => edit({ high_level_work: value })}
        />
        <LongField
          label={t("startRequirement")}
          value={draft.start_requirement}
          disabled={!editable}
          onChange={(value) => edit({ start_requirement: value })}
        />
      </BuilderSectionCard>

      {/*  ── 2. The method — Form 3's sixteen columns ────────────────────────────── */}
      <BuilderSectionCard
        id="method"
        accent="human"
        title={t("sections.method")}
        description={t("methodHelp")}
      >
        {draft.steps.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center">
            <p className="text-sm font-medium">{t("noStepsTitle")}</p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
              {t("noStepsBody")}
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {draft.steps.map((step, index) => (
              <JobStepCard
                key={index}
                step={step}
                index={index}
                total={draft.steps.length}
                lists={lists}
                disabled={!editable}
                onChange={(next) =>
                  edit({
                    steps: draft.steps.map((item, at) =>
                      at === index ? { ...item, ...next } : item,
                    ),
                  })
                }
                onRemove={() =>
                  edit({ steps: draft.steps.filter((_, at) => at !== index) })
                }
                onMove={(direction) => {
                  const target = index + direction;
                  if (target < 0 || target >= draft.steps.length) return;
                  const next = [...draft.steps];
                  const moved = next[index]!;
                  next[index] = next[target]!;
                  next[target] = moved;
                  edit({ steps: next });
                }}
              />
            ))}
          </ul>
        )}

        <Button
          icon={<Plus className="size-4" />}
          disabled={!editable}
          onClick={() =>
            edit({ steps: [...draft.steps, { mode: "human" } as Job["steps"][number]] })
          }
        >
          {t("addStep")}
        </Button>
      </BuilderSectionCard>

      {/*  ── 3. WHO — §8's multiple assignment rules ─────────────────────────────── */}
      <BuilderSectionCard
        id="who"
        accent="hybrid"
        title={t("sections.who")}
        description={t("whoHelp")}
      >
        <WhoRules
          rules={draft.assignment_rules as AssignmentRuleInput[]}
          disabled={!editable}
          onChange={(next) =>
            edit({ assignment_rules: next as Job["assignment_rules"] })
          }
        />
      </BuilderSectionCard>

      {/*  ── 4. Inputs — §8's typed definitions ──────────────────────────────────── */}
      <BuilderSectionCard
        id="inputs"
        accent="ai"
        title={t("sections.inputs")}
        description={t("inputsHelp")}
      >
        <JobInputs
          inputs={draft.inputs as JobInputDefinition[]}
          inputTypes={lists.input_types}
          disabled={!editable}
          onChange={(next) => edit({ inputs: next as Job["inputs"] })}
        />
      </BuilderSectionCard>

      {/*  ── 5. Evidence, quality and failure ────────────────────────────────────── */}
      <BuilderSectionCard
        id="quality"
        accent="approval"
        title={t("sections.quality")}
        description={t("qualityHelp")}
      >
        <LongField
          label={t("purpose")}
          value={draft.purpose}
          disabled={!editable}
          onChange={(value) => edit({ purpose: value })}
        />
        <LongField
          label={t("expectedOutput")}
          value={draft.expected_output}
          disabled={!editable}
          onChange={(value) => edit({ expected_output: value })}
        />
        <LongField
          label={t("completionEvidence")}
          value={draft.completion_evidence}
          disabled={!editable}
          onChange={(value) => edit({ completion_evidence: value })}
        />

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("normalCompletionTime")}>
            {(field) => (
              <Input
                {...field}
                value={draft.normal_completion_time ?? ""}
                disabled={!editable}
                onChange={(event) =>
                  edit({ normal_completion_time: event.target.value || null })
                }
              />
            )}
          </Field>
          <Suggest
            label={t("timeUnit")}
            value={draft.time_unit ?? ""}
            options={lists.time_units}
            disabled={!editable}
            onChange={(value) => edit({ time_unit: value || null })}
          />
          <Field label={t("sla")}>
            {(field) => (
              <Input
                {...field}
                value={draft.sla_note ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ sla_note: event.target.value || null })}
              />
            )}
          </Field>
        </div>

        <LongField
          label={t("qualityChecks")}
          value={draft.quality_checks}
          disabled={!editable}
          onChange={(value) => edit({ quality_checks: value })}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Suggest
            label={t("failureAction")}
            value={draft.failure_action ?? ""}
            options={lists.failure_actions}
            disabled={!editable}
            onChange={(value) => edit({ failure_action: value || null })}
          />
          <Suggest
            label={t("escalationTo")}
            value={draft.escalation_to ?? ""}
            options={lists.approvals}
            disabled={!editable}
            onChange={(value) => edit({ escalation_to: value || null })}
          />
        </div>
        <LongField
          label={t("retryPolicy")}
          value={draft.retry_policy}
          disabled={!editable}
          onChange={(value) => edit({ retry_policy: value })}
        />

        <PersonSelect
          label={t("approver")}
          value={draft.approver_membership_id}
          people={people}
          disabled={!editable}
          onChange={(value) => edit({ approver_membership_id: value })}
        />
        {draft.approver_membership_id &&
        draft.approver_membership_id === draft.owner_membership_id ? (
          <Alert tone="warning">{t("selfApprovalWarning")}</Alert>
        ) : null}
      </BuilderSectionCard>

      {/*  ── 6. Schedule — §8's auto-run ─────────────────────────────────────────── */}
      <BuilderSectionCard
        id="schedule"
        accent="hybrid"
        title={t("sections.schedule")}
        description={t("scheduleHelp")}
      >
        <ScheduleSection
          jobId={draft.id}
          editable={editable}
          timeZone={user?.timezone}
        />
      </BuilderSectionCard>

      {/*  ── 7. Publish ─────────────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="publish"
        accent="success"
        title={t("sections.publish")}
        description={t("publishHelp")}
      >
        <JobPublish jobId={draft.id} editable={editable} timeZone={user?.timezone} onChanged={onReload} />
      </BuilderSectionCard>
    </BuilderLayout>
  );
}

function stripReadFields(step: Job["steps"][number]): JobStepInput {
  const { id: _id, position: _position, depends_on: _depends, ...rest } = step;
  return rest;
}

/** What somebody typed while a save was in flight. Without this, the reply overwrites it. */
function unsavedSince(current: Job, sent: Job): Partial<Job> {
  const changed: Partial<Job> = {};
  for (const key of Object.keys(current) as (keyof Job)[]) {
    if (key === "version" || key === "updated_at" || key === "is_editable") continue;
    if (JSON.stringify(current[key]) !== JSON.stringify(sent[key])) {
      changed[key] = current[key] as never;
    }
  }
  return changed;
}

function StatusPill({ status }: { status: Job["status"] }) {
  const t = useTranslations("job");
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

/** The right column. Every line derived from the form — no percentages, no invented figures. */
function Guidance({ draft }: { draft: Job }) {
  const t = useTranslations("job");
  const exposed = draft.inputs.filter((item) => (item.ai_access ?? "none") !== "none").length;
  const unguarded = draft.steps.filter(
    (step) =>
      (step.mode === "ai_agent" || step.mode === "hybrid") &&
      !(step.if_missing_or_wrong ?? "").trim(),
  ).length;

  const todo = [
    draft.steps.length === 0 ? t("todoSteps") : null,
    draft.assignment_rules.length === 0 ? t("todoWho") : null,
    !draft.completion_evidence ? t("todoEvidence") : null,
    !draft.approver_membership_id ? t("todoApprover") : null,
    unguarded > 0 ? t("todoFallback", { count: unguarded }) : null,
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

        <div className="space-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
          <p>{t("stepsRecorded", { count: draft.steps.length })}</p>
          <p>{t("inputsDefined", { count: draft.inputs.length })}</p>
          {/*  The number people most want: what the AI can actually see. */}
          <p>{t("agentCanRead", { count: exposed })}</p>
        </div>
      </CardBody>
    </Card>
  );
}

/** Submit, withdraw and approve — the same three decisions as an Objective. */
function JobPublish({
  jobId,
  editable,
  timeZone,
  onChanged,
}: {
  jobId: string;
  editable: boolean;
  timeZone: string | undefined;
  onChanged: () => void;
}) {
  const t = useTranslations("job");
  const queryClient = useQueryClient();
  const format = contextFor(timeZone);

  const summary = useQuery({
    queryKey: ["job", jobId, "publish"],
    queryFn: ({ signal }) => fetchJobPublishSummary(jobId, signal),
  });
  const versions = useQuery({
    queryKey: ["job", jobId, "versions"],
    queryFn: ({ signal }) => fetchJobVersions(jobId, signal),
  });

  function reload() {
    void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    onChanged();
  }

  const submit = useMutation({
    mutationFn: (version: number) => submitJob(jobId, version),
    onSuccess: reload,
  });
  const withdraw = useMutation({
    mutationFn: (version: number) => withdrawJob(jobId, version),
    onSuccess: reload,
  });
  const approve = useMutation({
    mutationFn: (version: number) => publishJob(jobId, version),
    onSuccess: reload,
  });
  const failure = submit.error ?? withdraw.error ?? approve.error;

  return (
    <div className="space-y-4">
      <QueryStates
        isPending={summary.isPending}
        error={summary.error}
        onRetry={() => void summary.refetch()}
      >
        {summary.data ? (
          <>
            <div className="rounded-lg border border-border bg-muted/40 px-4 py-3">
              <p className="text-sm">{summary.data.next_action}</p>
            </div>

            <div className="flex flex-wrap gap-1.5 text-xs">
              <Badge tone="human">
                {t("humanSteps", { count: summary.data.human_steps })}
              </Badge>
              <Badge tone="ai">{t("agentSteps", { count: summary.data.agent_steps })}</Badge>
              <Badge tone="hybrid">
                {t("hybridSteps", { count: summary.data.hybrid_steps })}
              </Badge>
              <Badge tone={summary.data.ai_readable_inputs > 0 ? "ai" : "neutral"}>
                {t("agentCanRead", { count: summary.data.ai_readable_inputs })}
              </Badge>
            </div>

            {summary.data.schedule_summary ? (
              <p className="text-sm text-muted-foreground">
                {t("runsOn", { schedule: summary.data.schedule_summary })}
              </p>
            ) : null}

            {summary.data.warnings.length > 0 ? (
              <Alert tone="warning" title={t("worthKnowing")}>
                <ul className="mt-1 space-y-1">
                  {summary.data.warnings.map((warning) => (
                    <li key={warning.code}>{warning.message}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs">{t("warningsDoNotBlock")}</p>
              </Alert>
            ) : null}

            {failure ? <Alert tone="danger">{failure.message}</Alert> : null}

            <div className="flex flex-wrap items-center gap-2">
              {summary.data.can_submit ? (
                <Button
                  variant="primary"
                  icon={<Send className="size-4" />}
                  busy={submit.isPending}
                  onClick={() => submit.mutate(summary.data.version)}
                >
                  {t("sendForApproval")}
                </Button>
              ) : null}
              {summary.data.status === "ready_to_publish" && !editable ? (
                <Button
                  variant="ghost"
                  icon={<Undo2 className="size-4" />}
                  busy={withdraw.isPending}
                  onClick={() => withdraw.mutate(summary.data.version)}
                >
                  {t("withdraw")}
                </Button>
              ) : null}
              {summary.data.can_approve ? (
                <Button
                  variant="primary"
                  icon={<CheckCircle2 className="size-4" />}
                  busy={approve.isPending}
                  onClick={() => approve.mutate(summary.data.version)}
                >
                  {t("approveAndPublish")}
                </Button>
              ) : null}
            </div>
          </>
        ) : null}
      </QueryStates>

      {versions.data && versions.data.length > 0 ? (
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-semibold">{t("published")}</p>
          <ul className="mt-2 divide-y divide-border">
            {versions.data.map((version) => (
              <li key={version.id} className="flex flex-wrap items-baseline gap-x-3 py-2">
                <Badge tone="success">{t("versionNo", { no: version.version_no })}</Badge>
                <span className="text-sm">{version.name}</span>
                <span className="text-xs text-muted-foreground">
                  {t("approvedBy", { name: version.approved_by_name ?? "—" })} ·{" "}
                  {formatDateTime(version.published_at, format)}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t border-border pt-2 text-xs text-muted-foreground">
            {t("versionsAreImmutable")}
          </p>
        </div>
      ) : null}
    </div>
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
  const t = useTranslations("job");
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

function LongField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string | null | undefined;
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
