"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Save, Send, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useState, useRef } from "react";

import type {
  AgentUpdate,
  SandboxTestInput,
  Situation,
} from "@/lib/api/contract";
import {
  fetchAgent,
  fetchAgentLists,
  fetchAgentPublishSummary,
  fetchAgentVersions,
  fetchTests,
  grantTool,
  publishAgent,
  saveAgent,
  saveTests,
  submitAgent,
  withdrawAgent,
  type Agent,
  type AgentLists,
} from "@/lib/api/agents";
import { can } from "@/lib/api/auth";
import { useSession } from "@/lib/auth/use-session";
import { useAutosave } from "@/lib/builder/use-autosave";
import { contextFor, formatDate } from "@/lib/format";
import {
  Alert,
  Badge,
  Button,
  Field,
  Input,
  QueryStates,
  Textarea,
} from "@/ui";
import {
  DesignSteps,
  IoSchemas,
  KnowledgeSources,
  Situations,
  Tools,
} from "@/ui/builder/agent-sections";
import { PublishGates, SandboxTests } from "@/ui/builder/agent-tests";
import {
  BuilderLayout,
  BuilderSectionCard,
  type BuilderSection,
} from "@/ui/builder/builder-layout";
import { SkillRegistry } from "@/ui/builder/skill-registry";
import { Suggest } from "@/ui/builder/suggest";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * Agent Builder — the approved workbook's Form 4 and `PLAN.md` §9's ten form groups.
 *
 * On the same frame as the Objective and Job Builders, because §6 calls it the *shared* Builder
 * experience: same section rail, same save states, same sticky footer, same autosave rules.
 *
 * **The Skill Registry is a section of this screen, not a place.** §39: *"Skill Registry is
 * internal to Agent Builder and is not a sidebar module."* There is no route for it and §3
 * forbids a menu entry, so it lives in the rail beside Purpose and Controls.
 *
 * The section order follows what somebody knows when they sit down: what it is for, then what it
 * must never do, then the steps, then the skills, then the controls, then the tests.
 */
export default function AgentBuilderFormPage() {
  const t = useTranslations("agent");
  const params = useParams<{ id: string }>();
  const id = params.id;

  const agent = useQuery({
    queryKey: ["agent", id],
    queryFn: ({ signal }) => fetchAgent(id, signal),
  });
  const lists = useQuery({
    queryKey: ["agent", "lists"],
    queryFn: ({ signal }) => fetchAgentLists(signal),
    staleTime: 60 * 60 * 1000,
  });

  return (
    <AppShell
      title={t("builderTitle")}
      breadcrumb={[{ label: t("agents"), href: "/agent-builder" }]}
    >
      <QueryStates
        isPending={agent.isPending || lists.isPending}
        error={agent.error ?? lists.error}
        onRetry={() => void agent.refetch()}
      >
        {agent.data && lists.data ? (
          <Editor
            initial={agent.data}
            lists={lists.data}
            onReload={() => void agent.refetch()}
          />
        ) : null}
      </QueryStates>
    </AppShell>
  );
}

type SectionId =
  | "identity"
  | "purpose"
  | "design"
  | "skills"
  | "situations"
  | "controls"
  | "limits"
  | "publish";

function Editor({
  initial,
  lists,
  onReload,
}: {
  initial: Agent;
  lists: AgentLists;
  onReload: () => void;
}) {
  const t = useTranslations("agent");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useSession();
  const format = contextFor(user?.timezone);

  const [draft, setDraft] = useState<Agent>(initial);
  const [active, setActive] = useState<SectionId>("identity");
  const editable = draft.is_editable;

  //  The version the server last confirmed, held in a ref rather than read off the queued draft.
  //
  //  `autosave.schedule(next)` snapshots the draft as it was when somebody typed. If a save is
  //  already in flight, that snapshot carries the version from *before* it — stale by the time it
  //  is sent. And because the idempotency key is derived from the version, the second save reuses
  //  the first one's key with different content, which the server correctly refuses as a replay.
  //  The symptom is a save that fails for anybody who keeps typing while one is going out.
  //
  //  `expected_version` guards against **somebody else's** write, not against this client's own
  //  queued edit, so the right value is the newest version this client has been given.
  const confirmedVersion = useRef(draft.version);

  const send = useCallback(async (next: Agent) => {
    const payload: AgentUpdate = {
      name: next.name,
      trigger: next.trigger,
      frequency: next.frequency,
      completion_time_value: next.completion_time_value,
      completion_time_unit: next.completion_time_unit,
      purpose: next.purpose,
      instructions: next.instructions,
      boundaries: next.boundaries,
      prohibited_actions: next.prohibited_actions,
      visibility: next.visibility,
      model_policy_key: next.model_policy_key,
      main_approver_label: next.main_approver_label,
      escalation_label: next.escalation_label,
      cost_cap_minor_units: next.cost_cap_minor_units,
      cost_cap_currency: next.cost_cap_currency,
      token_cap: next.token_cap,
      time_limit_seconds: next.time_limit_seconds,
      max_concurrency: next.max_concurrency,
      max_retries: next.max_retries,
      steps: next.steps.map(({ id: _id, ...rest }) => rest),
      escalation_rules: next.escalation_rules.map(
        ({ id: _id, label: _label, ...rest }) => rest,
      ),
      io_schemas: next.io_schemas.map(({ id: _id, ...rest }) => rest),
      knowledge_sources: next.knowledge_sources.map(({ id: _id, ...rest }) => rest),
      tools: next.tools.map(({ position, tool, scopes, purpose }) => ({
        position,
        tool,
        scopes,
        purpose,
      })),
      skills: next.skills.map(({ position, skill_id, resolver_decision_id, notes }) => ({
        position,
        skill_id,
        resolver_decision_id,
        notes,
      })),
      expected_version: confirmedVersion.current,
    };
    const saved = await saveAgent(next.id, payload);
    confirmedVersion.current = saved.version;
    //  The server's copy wins, except for anything typed while the request was out.
    setDraft((current) => ({ ...saved, name: current.name === next.name ? saved.name : current.name }));
    //  Saving clears every recorded test result, so the panel that shows them has to be refetched
    //  rather than left displaying passes that no longer apply.
    void queryClient.invalidateQueries({ queryKey: ["agent-tests", next.id] });
    void queryClient.invalidateQueries({ queryKey: ["agent-publish", next.id] });
  }, [queryClient]);

  const autosave = useAutosave<Agent>(send, { enabled: editable });

  const edit = useCallback(
    (patch: Partial<Agent>) => {
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
        complete: Boolean(draft.name && draft.trigger),
      },
      {
        id: "purpose",
        label: t("sections.purpose"),
        complete: Boolean(draft.purpose && draft.prohibited_actions),
        attention: !draft.prohibited_actions,
      },
      {
        id: "design",
        label: t("sections.design"),
        complete: draft.steps.length > 0,
        attention: draft.steps.length === 0,
      },
      { id: "skills", label: t("sections.skills"), complete: draft.skills.length > 0 },
      {
        id: "situations",
        label: t("sections.situations"),
        complete: draft.situations_unanswered.length === 0,
        attention: draft.situations_unanswered.length > 0,
      },
      { id: "controls", label: t("sections.controls") },
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
          {draft.job_name ? (
            <>
              <span aria-hidden>·</span>
              <span>
                {draft.job_version_no
                  ? t("runsJobVersion", {
                      name: draft.job_name,
                      version: draft.job_version_no,
                    })
                  : t("forJobUnpublished", { name: draft.job_name })}
              </span>
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
            onClick={() => router.push("/agent-builder")}
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

      {/*  ── 1. Identity — Form 4's header ──────────────────────────────────────── */}
      <BuilderSectionCard id="identity" title={t("sections.identity")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("field.name")} htmlFor="agent-name" required>
            {(field) => (
              <Input
                {...field}
                value={draft.name}
                disabled={!editable}
                onChange={(event) => edit({ name: event.target.value })}
              />
            )}
          </Field>
          <Suggest
            label={t("field.trigger")}
            value={draft.trigger ?? ""}
            options={lists.triggers}
            disabled={!editable}
            onChange={(value) => edit({ trigger: value || null })}
          />
          <Suggest
            label={t("field.frequency")}
            value={draft.frequency ?? ""}
            options={lists.frequencies}
            disabled={!editable}
            onChange={(value) => edit({ frequency: value || null })}
          />
          <div className="flex gap-2">
            <Field label={t("field.completionTime")}>
              {(field) => (
                <Input
                  {...field}
                  type="number"
                  min={1}
                  value={draft.completion_time_value ?? ""}
                  disabled={!editable}
                  onChange={(event) =>
                    edit({
                      completion_time_value: event.target.value
                        ? Number(event.target.value)
                        : null,
                    })
                  }
                />
              )}
            </Field>
            <div className="w-32">
              <Suggest
                label={t("field.timeUnit")}
                value={draft.completion_time_unit ?? ""}
                options={lists.time_units}
                disabled={!editable}
                onChange={(value) => edit({ completion_time_unit: value || null })}
              />
            </div>
          </div>
        </div>
      </BuilderSectionCard>

      {/*  ── 2. Purpose, boundaries, prohibitions — §9 group 2 ──────────────────── */}
      <BuilderSectionCard
        id="purpose"
        title={t("sections.purpose")}
        description={t("purposeDescription")}
      >
        <div className="space-y-4">
          <Field label={t("field.purpose")}>
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
          <Field label={t("field.instructions")} hint={t("instructionsHint")}>
            {(field) => (
              <Textarea
                {...field}
                rows={4}
                value={draft.instructions ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ instructions: event.target.value || null })}
              />
            )}
          </Field>
          <Field label={t("field.boundaries")}>
            {(field) => (
              <Textarea
                {...field}
                rows={2}
                value={draft.boundaries ?? ""}
                disabled={!editable}
                onChange={(event) => edit({ boundaries: event.target.value || null })}
              />
            )}
          </Field>
          {/*  Coloured, because it is the sentence a reviewer reads first. */}
          <div className="rounded-lg border border-approval bg-approval-soft p-3">
            <Field label={t("field.prohibitedActions")} hint={t("prohibitedHint")}>
              {(field) => (
                <Textarea
                  {...field}
                  rows={2}
                  value={draft.prohibited_actions ?? ""}
                  disabled={!editable}
                  onChange={(event) =>
                    edit({ prohibited_actions: event.target.value || null })
                  }
                />
              )}
            </Field>
          </div>
        </div>
      </BuilderSectionCard>

      {/*  ── 3. Form 4 section A ─────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="design"
        title={t("sections.design")}
        letter={t("sectionLetter.design")}
        flush
        description={t("designDescription")}
      >
        <DesignSteps
          steps={draft.steps.map(({ id: _id, ...rest }) => rest)}
          approvals={lists.approvals}
          disabled={!editable}
          onChange={(steps) =>
            edit({ steps: steps as unknown as Agent["steps"] })
          }
        />
      </BuilderSectionCard>

      {/*  ── 4. The Skill Registry, inside the Builder — §39 ──────────────────────── */}
      <BuilderSectionCard
        id="skills"
        title={t("sections.skills")}
        description={t("skillsDescription")}
      >
        <SkillRegistry
          attached={draft.skills}
          department={null}
          industry={null}
          disabled={!editable}
          onAttach={(skillId, decisionId) => {
            if (draft.skills.some((row) => row.skill_id === skillId)) return;
            edit({
              skills: [
                ...draft.skills,
                {
                  id: `pending-${skillId}`,
                  position: draft.skills.length + 1,
                  skill_id: skillId,
                  name: "",
                  catalogue_id: null,
                  autonomy: "",
                  exclusions: null,
                  resolver_decision_id: decisionId,
                  //  Never set here. The route is copied from the decision by the server, so a
                  //  screen cannot record a candidate as reused when the resolver blocked it.
                  route: null,
                  notes: null,
                },
              ],
            });
          }}
          onDetach={(skillId) =>
            edit({
              skills: draft.skills
                .filter((row) => row.skill_id !== skillId)
                .map((row, index) => ({ ...row, position: index + 1 })),
            })
          }
        />
      </BuilderSectionCard>

      {/*  ── 5. Form 4 section B ─────────────────────────────────────────────────── */}
      <BuilderSectionCard
        id="situations"
        title={t("sections.situations")}
        letter={t("sectionLetter.situations")}
        description={t("situationsDescription")}
      >
        <Situations
          rules={draft.escalation_rules.map(({ id: _id, label: _label, ...rest }) => rest)}
          situations={lists.situations.map((entry) => ({
            value: String(entry.value ?? "") as Situation,
            label: String(entry.label ?? ""),
          }))}
          disabled={!editable}
          onChange={(rules) =>
            edit({
              escalation_rules: rules as unknown as Agent["escalation_rules"],
            })
          }
        />
      </BuilderSectionCard>

      {/*  ── 6. Controls — §9 groups 4, 6 and 7 ──────────────────────────────────── */}
      <BuilderSectionCard
        id="controls"
        title={t("sections.controls")}
        description={t("controlsDescription")}
      >
        <ControlsSection
          draft={draft}
          lists={lists}
          editable={editable}
          onEdit={edit}
          onReload={onReload}
        />
      </BuilderSectionCard>

      {/*  ── 7. Limits, model policy, audience — §9 groups 3, 5 and 9 ────────────── */}
      <BuilderSectionCard
        id="limits"
        title={t("sections.limits")}
        description={t("limitsDescription")}
      >
        <LimitsSection draft={draft} lists={lists} editable={editable} onEdit={edit} />
      </BuilderSectionCard>

      {/*  ── 8. Form 4 section C, the two gates, and publish ─────────────────────── */}
      <BuilderSectionCard
        id="publish"
        title={t("sections.publish")}
        letter={t("sectionLetter.publish")}
      >
        <PublishSection draft={draft} onReload={onReload} />
      </BuilderSectionCard>
    </BuilderLayout>
  );
}

// ---------------------------------------------------------------------------- controls

function ControlsSection({
  draft,
  lists,
  editable,
  onEdit,
  onReload,
}: {
  draft: Agent;
  lists: AgentLists;
  editable: boolean;
  onEdit: (patch: Partial<Agent>) => void;
  onReload: () => void;
}) {
  const t = useTranslations("agent");
  const { user } = useSession();
  const queryClient = useQueryClient();
  const [granting, setGranting] = useState<string | null>(null);

  const grant = useMutation({
    mutationFn: ({ toolId, granted }: { toolId: string; granted: boolean }) =>
      grantTool(draft.id, toolId, granted, draft.version),
    onSettled: () => {
      setGranting(null);
      void queryClient.invalidateQueries({ queryKey: ["agent", draft.id] });
      onReload();
    },
  });

  return (
    <div className="space-y-8">
      <section aria-labelledby="tools-heading" className="space-y-3">
        <h3 id="tools-heading" className="text-sm font-semibold">
          {t("toolsTitle")}
        </h3>
        <Tools
          tools={draft.tools.map(({ position, tool, scopes, purpose }) => ({
            position,
            tool,
            scopes,
            purpose,
          }))}
          saved={draft.tools}
          permissions={lists.permissions}
          disabled={!editable}
          mayGrant={can(user, "manage_access")}
          granting={granting}
          onChange={(tools) => onEdit({ tools: tools as unknown as Agent["tools"] })}
          onGrant={(toolId, granted) => {
            setGranting(toolId);
            grant.mutate({ toolId, granted });
          }}
        />
        {grant.isError ? (
          <Alert tone="danger">
            {grant.error instanceof Error ? grant.error.message : t("grantFailed")}
          </Alert>
        ) : null}
      </section>

      <section aria-labelledby="io-heading" className="space-y-3">
        <h3 id="io-heading" className="text-sm font-semibold">
          {t("ioTitle")}
        </h3>
        <IoSchemas
          rows={draft.io_schemas.map(({ id: _id, ...rest }) => rest)}
          inputTypes={lists.input_types}
          outputFormats={lists.output_formats}
          disabled={!editable}
          onChange={(rows) =>
            onEdit({ io_schemas: rows as unknown as Agent["io_schemas"] })
          }
        />
      </section>

      <section aria-labelledby="knowledge-heading" className="space-y-3">
        <h3 id="knowledge-heading" className="text-sm font-semibold">
          {t("knowledgeTitle")}
        </h3>
        <KnowledgeSources
          rows={draft.knowledge_sources.map(({ id: _id, ...rest }) => rest)}
          locations={lists.locations}
          disabled={!editable}
          onChange={(rows) =>
            onEdit({ knowledge_sources: rows as unknown as Agent["knowledge_sources"] })
          }
        />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------- limits

function LimitsSection({
  draft,
  lists,
  editable,
  onEdit,
}: {
  draft: Agent;
  lists: AgentLists;
  editable: boolean;
  onEdit: (patch: Partial<Agent>) => void;
}) {
  const t = useTranslations("agent");

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("field.audience")} hint={t("audienceHint")}>
          {(field) => (
            <select
              {...field}
              value={draft.visibility}
              disabled={!editable}
              onChange={(event) =>
                onEdit({ visibility: event.target.value as Agent["visibility"] })
              }
              className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm"
            >
              {lists.visibility.map((option) => (
                <option key={option} value={option}>
                  {t(`audience.${option}`)}
                </option>
              ))}
            </select>
          )}
        </Field>

        {/*  A key the gateway resolves, never a model name. No approved catalogue exists yet, so
            this is a free field and the hint says why rather than offering invented choices. */}
        <Field label={t("field.modelPolicy")} hint={t("modelPolicyHint")}>
          {(field) => (
            <Input
              {...field}
              value={draft.model_policy_key ?? ""}
              disabled={!editable}
              onChange={(event) =>
                onEdit({ model_policy_key: event.target.value || null })
              }
            />
          )}
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Suggest
          label={t("field.mainApprover")}
          value={draft.main_approver_label ?? ""}
          options={lists.approvals}
          disabled={!editable}
          onChange={(value) => onEdit({ main_approver_label: value || null })}
        />
        <Suggest
          label={t("field.escalationTo")}
          value={draft.escalation_label ?? ""}
          options={lists.approvals}
          disabled={!editable}
          onChange={(value) => onEdit({ escalation_label: value || null })}
        />
      </div>

      <fieldset disabled={!editable} className="space-y-3">
        <legend className="text-sm font-semibold">{t("limitsTitle")}</legend>
        <p className="text-sm text-muted-foreground">{t("limitsHint")}</p>
        <div className="grid gap-4 sm:grid-cols-3">
          {(
            [
              ["token_cap", t("field.tokenCap")],
              ["time_limit_seconds", t("field.timeLimit")],
              ["max_concurrency", t("field.concurrency")],
              ["max_retries", t("field.retries")],
            ] as const
          ).map(([key, label]) => (
            <Field key={key} label={label}>
              {(field) => (
                <Input
                  {...field}
                  type="number"
                  min={key === "max_retries" ? 0 : 1}
                  value={draft[key] ?? ""}
                  onChange={(event) =>
                    onEdit({
                      [key]: event.target.value ? Number(event.target.value) : null,
                    } as Partial<Agent>)
                  }
                />
              )}
            </Field>
          ))}
        </div>
      </fieldset>
    </div>
  );
}

// ---------------------------------------------------------------------------- publish

function PublishSection({ draft, onReload }: { draft: Agent; onReload: () => void }) {
  const t = useTranslations("agent");
  const { user } = useSession();
  const queryClient = useQueryClient();

  const tests = useQuery({
    queryKey: ["agent-tests", draft.id],
    queryFn: ({ signal }) => fetchTests(draft.id, signal),
  });
  const summary = useQuery({
    queryKey: ["agent-publish", draft.id],
    queryFn: ({ signal }) => fetchAgentPublishSummary(draft.id, signal),
  });
  const versions = useQuery({
    queryKey: ["agent-versions", draft.id],
    queryFn: ({ signal }) => fetchAgentVersions(draft.id, signal),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["agent", draft.id] });
    void queryClient.invalidateQueries({ queryKey: ["agent-tests", draft.id] });
    void queryClient.invalidateQueries({ queryKey: ["agent-publish", draft.id] });
    void queryClient.invalidateQueries({ queryKey: ["agent-versions", draft.id] });
    onReload();
  };

  const record = useMutation({
    mutationFn: (next: SandboxTestInput[]) => saveTests(draft.id, next, draft.version),
    onSuccess: refresh,
  });
  const submit = useMutation({
    mutationFn: () => submitAgent(draft.id, draft.version),
    onSuccess: refresh,
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawAgent(draft.id, draft.version),
    onSuccess: refresh,
  });
  const publish = useMutation({
    mutationFn: () => publishAgent(draft.id, draft.version),
    onSuccess: refresh,
  });

  const failed = [record, submit, withdraw, publish].find((mutation) => mutation.isError);

  return (
    <div className="space-y-6">
      {/*  A failed request renders as a failure. Never a toast claiming it worked. */}
      {failed ? (
        <Alert tone="danger">
          {failed.error instanceof Error ? failed.error.message : t("actionFailed")}
        </Alert>
      ) : null}

      <QueryStates
        isPending={tests.isPending}
        error={tests.error}
        onRetry={() => void tests.refetch()}
      >
        {tests.data ? (
          <SandboxTests
            tests={tests.data}
            disabled={!draft.is_editable}
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
                  //  Disabled while a gate is closed, with the gate's own reason above. A button
                  //  that submitted into a queue nobody could approve teaches people to ignore it.
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

              {summary.data.can_approve && can(user, "publish") ? (
                <Button
                  variant="primary"
                  icon={<CheckCircle2 className="size-4" />}
                  busy={publish.isPending}
                  onClick={() => publish.mutate()}
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

function StatusPill({ status }: { status: string }) {
  const t = useTranslations("agent");
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
