"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Plus, Send, ShieldCheck, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { fetchPeople } from "@/lib/api/objectives";
import type {
  SkillDraft,
  SkillDraftSummary,
  SkillGap,
  SkillRuleInput,
  SkillTestKind,
  SkillTestRead,
} from "@/lib/api/contract";
import {
  approveSkillDraft,
  archiveSkillDraft,
  createSkillDraft,
  fetchSkillDraft,
  fetchSkillDraftSummary,
  fetchSkillDrafts,
  nameSkillApprover,
  recordSkillTestResult,
  saveSkillDraft,
  submitSkillDraft,
  withdrawSkillDraft,
  writeSkillTest,
} from "@/lib/api/skill-drafts";
import { cn } from "@/lib/cn";
import { Alert, Badge, Button, Field, Input, QueryStates, Textarea } from "@/ui";
import { PersonSelect } from "@/ui/builder/person-select";

/**
 * *"Private Skill Drafts"* — the third thing under Skills in `docs/product/SKILL_REGISTRY.md`'s
 * own tree, beside Registry and Resolver, and inside the Agent Builder because §39 says the
 * registry is not a sidebar module.
 *
 * ## What this screen is for
 *
 * The resolver has been able to answer *Create a private Skill Draft* since 5.2 — *"Start a private
 * Skill Draft for the gap"* — with nothing at the other end of the sentence. This is the other end:
 * §39's last three arrows, in order.
 *
 *     Create private Skill Draft → Sandbox tests → Human approval → Versioned active Skill
 *
 * ## Why the gaps are listed rather than the button simply disabled
 *
 * `can_submit` and every gap come from the backend, which is the only place that can be right about
 * them. A disabled button with no explanation teaches people to guess; each gap here names the
 * field **and why the resolver needs it** — because a skill approved without its evidence source is
 * refused by every resolution afterwards, and nobody finds out for months.
 *
 * ## Why the six tests are a table and not a checklist
 *
 * A checkbox records that somebody ticked it. These record what the test was, what should have
 * happened, what did, who ran it and when — which is what makes a passing skill's approval mean
 * something. There is no sandbox runtime for a skill yet, and the panel says so rather than
 * implying the product ran anything.
 */
export function SkillDrafts({ disabled }: { disabled: boolean }) {
  const t = useTranslations("factory");
  const [openId, setOpenId] = useState<string | null>(null);

  const drafts = useQuery({
    queryKey: ["skill-drafts"],
    queryFn: ({ signal }) => fetchSkillDrafts(signal),
  });

  if (openId) {
    return <DraftEditor id={openId} disabled={disabled} onClose={() => setOpenId(null)} />;
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t("intro")}</p>

      <NewDraft disabled={disabled} onCreated={setOpenId} />

      <QueryStates
        isPending={drafts.isPending}
        error={drafts.error}
        isEmpty={drafts.data?.is_empty ?? false}
        emptyTitle={t("emptyTitle")}
        emptyDescription={t("emptyBody")}
        onRetry={() => void drafts.refetch()}
      >
        <ul className="space-y-2">
          {(drafts.data?.drafts ?? []).map((card) => (
            <li key={card.id}>
              <button
                type="button"
                onClick={() => setOpenId(card.id)}
                className={cn(
                  "flex w-full items-start justify-between gap-3 rounded-lg border border-border",
                  "bg-card p-3 text-left hover:bg-accent",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{card.name}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {/*  Two counts, never a percentage: six tests written down and how many
                        passed is a fact, and a proportion of a fixed six adds nothing. */}
                    {t("cardCounts", { rules: card.rule_count, passed: card.tests_passed })}
                    {card.owner_name ? ` · ${card.owner_name}` : ""}
                  </span>
                </span>
                <StatusBadge status={card.status} />
              </button>
            </li>
          ))}
        </ul>
      </QueryStates>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("factory");
  const tone =
    status === "published"
      ? "success"
      : status === "ready_to_publish"
        ? "approval"
        : status === "archived"
          ? "neutral"
          : "ai";
  return (
    <Badge tone={tone as "success" | "approval" | "neutral" | "ai"}>
      {t(`status.${status}` as "status.draft")}
    </Badge>
  );
}

function NewDraft({
  disabled,
  onCreated,
}: {
  disabled: boolean;
  onCreated: (id: string) => void;
}) {
  const t = useTranslations("factory");
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);

  const create = useMutation({
    mutationFn: () => createSkillDraft({ name: name.trim() }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["skill-drafts"] });
      setName("");
      setOpen(false);
      onCreated(result.id);
    },
  });

  if (!open) {
    return (
      <Button
        variant="secondary"
        size="sm"
        disabled={disabled}
        icon={<Plus className="size-3.5" />}
        onClick={() => setOpen(true)}
      >
        {t("newDraft")}
      </Button>
    );
  }

  return (
    <form
      className="space-y-2 rounded-lg border border-border bg-card p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <Field label={t("draftName")} hint={t("draftNameHint")} htmlFor="new-skill-draft" required>
        {(field) => (
          <Input
            {...field}
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        )}
      </Field>
      {create.isError ? (
        <Alert tone="danger" title={t("couldNotCreate")}>
          {(create.error as Error).message}
        </Alert>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" size="sm" busy={create.isPending} disabled={!name.trim()}>
          {t("start")}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}

/** The ten fields the submit gate asks for, in the order somebody would write them. */
const FIELDS = [
  { name: "purpose", rows: 2 },
  { name: "positive_trigger", rows: 2 },
  { name: "exclusions", rows: 2 },
  { name: "minimum_inputs", rows: 2 },
  { name: "primary_if", rows: 2 },
  { name: "primary_then", rows: 2 },
  { name: "output", rows: 2 },
  { name: "validation_gate", rows: 2 },
  { name: "source_ids", rows: 2 },
] as const;

function DraftEditor({
  id,
  disabled,
  onClose,
}: {
  id: string;
  disabled: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("factory");
  const queryClient = useQueryClient();

  const draft = useQuery({
    queryKey: ["skill-draft", id],
    queryFn: ({ signal }) => fetchSkillDraft(id, signal),
  });
  const summary = useQuery({
    queryKey: ["skill-draft-summary", id],
    queryFn: ({ signal }) => fetchSkillDraftSummary(id, signal),
  });
  const people = useQuery({
    queryKey: ["people"],
    queryFn: ({ signal }) => fetchPeople(signal),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["skill-draft", id] });
    void queryClient.invalidateQueries({ queryKey: ["skill-draft-summary", id] });
    void queryClient.invalidateQueries({ queryKey: ["skill-drafts"] });
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onClose}>
        {t("backToList")}
      </Button>

      <QueryStates
        isPending={draft.isPending || summary.isPending}
        error={draft.error ?? summary.error}
        isEmpty={false}
        emptyTitle=""
        onRetry={() => {
          void draft.refetch();
          void summary.refetch();
        }}
      >
        {draft.data && summary.data ? (
          <>
            <header className="space-y-1">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold">{draft.data.name}</h3>
                <StatusBadge status={draft.data.status} />
              </div>
              <p className="text-xs text-muted-foreground">
                {summary.data.next_action}
                {draft.data.published_version_no
                  ? ` · ${t("versionIs", { version: draft.data.published_version_no })}`
                  : ""}
              </p>
            </header>

            <Fields draft={draft.data} disabled={disabled} onSaved={refresh} />
            <Rules draft={draft.data} disabled={disabled} onSaved={refresh} />
            <Tests draft={draft.data} disabled={disabled} onSaved={refresh} />

            <Decision
              draft={draft.data}
              summary={summary.data}
              people={people.data ?? []}
              disabled={disabled}
              onDone={refresh}
            />
          </>
        ) : null}
      </QueryStates>
    </div>
  );
}

function Fields({
  draft,
  disabled,
  onSaved,
}: {
  draft: SkillDraft;
  disabled: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations("factory");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      FIELDS.map((entry) => [entry.name, (draft[entry.name] as string | null) ?? ""]),
    ),
  );

  const save = useMutation({
    mutationFn: () =>
      saveSkillDraft(draft.id, {
        expected_version: draft.version,
        ...Object.fromEntries(
          Object.entries(values).map(([key, value]) => [key, value.trim() || null]),
        ),
      }),
    onSuccess: onSaved,
  });

  const locked = disabled || !draft.is_editable;

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-3">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("theSkill")}
      </h4>
      {FIELDS.map((entry) => (
        <Field
          key={entry.name}
          label={t(`field.${entry.name}` as "field.purpose")}
          hint={t(`hint.${entry.name}` as "hint.purpose")}
          htmlFor={`skill-${entry.name}`}
          required
        >
          {(field) => (
            <Textarea
              {...field}
              rows={entry.rows}
              value={values[entry.name] ?? ""}
              disabled={locked}
              onChange={(event) =>
                setValues((previous) => ({ ...previous, [entry.name]: event.target.value }))
              }
            />
          )}
        </Field>
      ))}
      {save.isError ? (
        <Alert tone="danger" title={t("couldNotSave")}>
          {(save.error as Error).message}
        </Alert>
      ) : null}
      {!locked ? (
        <Button
          variant="secondary"
          size="sm"
          busy={save.isPending}
          onClick={() => save.mutate()}
        >
          {t("save")}
        </Button>
      ) : (
        <p className="text-xs text-muted-foreground">{t("notEditable")}</p>
      )}
    </section>
  );
}

/**
 * The IF-THEN decisions.
 *
 * `failure_state` is offered on every rule because it is what makes a rule governance rather than
 * logic: it is the sentence the product says when the rule refuses, in the author's own words —
 * the same field the catalogue's 2,400 rules carry and the reason they were worth importing.
 */
function Rules({
  draft,
  disabled,
  onSaved,
}: {
  draft: SkillDraft;
  disabled: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations("factory");
  const [rules, setRules] = useState<SkillRuleInput[]>(() =>
    draft.rules.map((rule) => ({
      condition_type: rule.condition_type,
      if_clause: rule.if_clause,
      then_clause: rule.then_clause,
      priority: rule.priority,
      evidence_required: rule.evidence_required,
      failure_state: rule.failure_state,
      human_gate: rule.human_gate,
      source_ids: rule.source_ids,
    })),
  );

  const save = useMutation({
    mutationFn: () => saveSkillDraft(draft.id, { expected_version: draft.version, rules }),
    onSuccess: onSaved,
  });

  const locked = disabled || !draft.is_editable;

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-3">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("rules")}
      </h4>
      {rules.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("noRules")}</p>
      ) : null}
      {rules.map((rule, index) => (
        <div key={index} className="space-y-2 rounded-md border border-border p-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label={t("ifClause")} htmlFor={`rule-if-${index}`} required>
              {(field) => (
                <Textarea
                  {...field}
                  rows={2}
                  value={rule.if_clause}
                  disabled={locked}
                  onChange={(event) =>
                    setRules((previous) =>
                      previous.map((row, at) =>
                        at === index ? { ...row, if_clause: event.target.value } : row,
                      ),
                    )
                  }
                />
              )}
            </Field>
            <Field label={t("thenClause")} htmlFor={`rule-then-${index}`} required>
              {(field) => (
                <Textarea
                  {...field}
                  rows={2}
                  value={rule.then_clause}
                  disabled={locked}
                  onChange={(event) =>
                    setRules((previous) =>
                      previous.map((row, at) =>
                        at === index ? { ...row, then_clause: event.target.value } : row,
                      ),
                    )
                  }
                />
              )}
            </Field>
          </div>
          <Field
            label={t("failureState")}
            hint={t("failureStateHint")}
            htmlFor={`rule-failure-${index}`}
          >
            {(field) => (
              <Input
                {...field}
                value={rule.failure_state ?? ""}
                disabled={locked}
                onChange={(event) =>
                  setRules((previous) =>
                    previous.map((row, at) =>
                      at === index ? { ...row, failure_state: event.target.value } : row,
                    ),
                  )
                }
              />
            )}
          </Field>
          {!locked ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRules((previous) => previous.filter((_, at) => at !== index))}
            >
              {t("removeRule")}
            </Button>
          ) : null}
        </div>
      ))}
      {save.isError ? (
        <Alert tone="danger" title={t("couldNotSave")}>
          {(save.error as Error).message}
        </Alert>
      ) : null}
      {!locked ? (
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus className="size-3.5" />}
            onClick={() =>
              setRules((previous) => [
                ...previous,
                {
                  condition_type: "primary decision",
                  if_clause: "",
                  then_clause: "",
                  priority: "High",
                  evidence_required: null,
                  failure_state: null,
                  human_gate: null,
                  source_ids: null,
                },
              ])
            }
          >
            {t("addRule")}
          </Button>
          <Button variant="secondary" size="sm" busy={save.isPending} onClick={() => save.mutate()}>
            {t("saveRules")}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

const RESULT_ICON = {
  pass: CheckCircle2,
  fail: XCircle,
  blocked: XCircle,
  not_run: Circle,
} as const;

function Tests({
  draft,
  disabled,
  onSaved,
}: {
  draft: SkillDraft;
  disabled: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations("factory");

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-3">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("tests")}
        </h4>
        {/*  Said plainly: the product did not run these. A panel that showed six green ticks
            without saying who put them there would be claiming a sandbox it does not have. */}
        <p className="mt-1 text-xs text-muted-foreground">{t("testsNoRuntime")}</p>
      </div>
      {draft.tests.map((test) => (
        <TestRow
          key={test.kind}
          draft={draft}
          test={test}
          disabled={disabled}
          onSaved={onSaved}
        />
      ))}
    </section>
  );
}

function TestRow({
  draft,
  test,
  disabled,
  onSaved,
}: {
  draft: SkillDraft;
  test: SkillTestRead;
  disabled: boolean;
  onSaved: () => void;
}) {
  const t = useTranslations("factory");
  const [situation, setSituation] = useState(test.sample_situation ?? "");
  const [expected, setExpected] = useState(test.expected_result ?? "");
  const [observed, setObserved] = useState("");
  const locked = disabled || !draft.is_editable;
  const Icon = RESULT_ICON[test.status as keyof typeof RESULT_ICON] ?? Circle;

  const write = useMutation({
    mutationFn: () =>
      writeSkillTest(draft.id, test.kind as SkillTestKind, {
        sample_situation: situation.trim() || null,
        expected_result: expected.trim() || null,
      }),
    onSuccess: onSaved,
  });
  const record = useMutation({
    mutationFn: (status: "pass" | "fail" | "blocked") =>
      recordSkillTestResult(draft.id, test.kind as SkillTestKind, { status, observed }),
    onSuccess: () => {
      setObserved("");
      onSaved();
    },
  });

  return (
    <div className="space-y-2 rounded-md border border-border p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <Icon
            aria-hidden
            className={cn(
              "size-4",
              test.status === "pass" ? "text-success" : "text-muted-foreground",
            )}
          />
          {t(`test.${test.kind}` as "test.golden")}
        </span>
        <span className="text-xs text-muted-foreground">
          {t(`result.${test.status}` as "result.not_run")}
          {test.run_by_name ? ` · ${test.run_by_name}` : ""}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{t(`testWhy.${test.kind}` as "testWhy.golden")}</p>

      <div className="grid gap-2 sm:grid-cols-2">
        <Field label={t("situation")} htmlFor={`test-situation-${test.kind}`}>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={situation}
              disabled={locked}
              onChange={(event) => setSituation(event.target.value)}
            />
          )}
        </Field>
        <Field label={t("shouldHappen")} htmlFor={`test-expected-${test.kind}`}>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={expected}
              disabled={locked}
              onChange={(event) => setExpected(event.target.value)}
            />
          )}
        </Field>
      </div>

      {test.actual_result ? (
        <p className="rounded bg-muted/50 px-2 py-1 text-xs">
          {t("whatHappened")}: {test.actual_result}
        </p>
      ) : null}

      {write.isError || record.isError ? (
        <Alert tone="danger" title={t("couldNotSave")}>
          {((write.error ?? record.error) as Error).message}
        </Alert>
      ) : null}

      {!locked ? (
        <div className="space-y-2">
          <Button variant="secondary" size="sm" busy={write.isPending} onClick={() => write.mutate()}>
            {t("saveTest")}
          </Button>

          {/*  A result needs an observation. The button is held back until there is one, because
              the backend refuses a pass nobody can check — and so does the table. */}
          <Field label={t("whatHappened")} hint={t("observedHint")} htmlFor={`test-observed-${test.kind}`}>
            {(field) => (
              <Textarea
                {...field}
                rows={2}
                value={observed}
                onChange={(event) => setObserved(event.target.value)}
              />
            )}
          </Field>
          <div className="flex flex-wrap gap-2">
            {(["pass", "fail", "blocked"] as const).map((status) => (
              <Button
                key={status}
                variant="secondary"
                size="sm"
                busy={record.isPending}
                disabled={!observed.trim()}
                onClick={() => record.mutate(status)}
              >
                {t(`record.${status}` as "record.pass")}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Naming the approver, sending it, and — for somebody else — deciding.
 *
 * Every button here is driven by `can_submit` / `can_approve` from the backend. §39: *"No Skill or
 * Agent can approve/promote itself"*, so the person who sent it sees no approve button at all, and
 * would be refused by the service if they found one.
 */
function Decision({
  draft,
  summary,
  people,
  disabled,
  onDone,
}: {
  draft: SkillDraft;
  summary: SkillDraftSummary;
  people: { membership_id: string; display_name: string; job_title?: string | null }[];
  disabled: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("factory");

  const name = useMutation({
    mutationFn: (membershipId: string) =>
      nameSkillApprover(draft.id, membershipId, draft.version),
    onSuccess: onDone,
  });
  const send = useMutation({
    mutationFn: () => submitSkillDraft(draft.id, draft.version),
    onSuccess: onDone,
  });
  const takeBack = useMutation({
    mutationFn: () => withdrawSkillDraft(draft.id, draft.version),
    onSuccess: onDone,
  });
  const decide = useMutation({
    mutationFn: () => approveSkillDraft(draft.id, draft.version),
    onSuccess: onDone,
  });
  const retire = useMutation({
    mutationFn: () => archiveSkillDraft(draft.id, draft.version),
    onSuccess: onDone,
  });

  const failed = [name, send, takeBack, decide, retire].find((one) => one.isError);

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-3">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("approval")}
      </h4>

      {draft.is_editable ? (
        <PersonSelect
          label={t("approver")}
          hint={t("approverHint")}
          value={draft.approver_membership_id}
          people={people}
          disabled={disabled || name.isPending}
          onChange={(value) => {
            if (value) name.mutate(value);
          }}
        />
      ) : (
        <p className="text-sm">
          {t("approverIs", { name: draft.approver_name ?? t("nobody") })}
          {draft.submitted_by_name
            ? ` · ${t("sentBy", { name: draft.submitted_by_name })}`
            : ""}
        </p>
      )}

      <Gaps gaps={summary.gaps} />

      {failed ? (
        <Alert tone="danger" title={t("couldNotDo")}>
          {(failed.error as Error).message}
        </Alert>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {summary.can_submit ? (
          <Button
            variant="primary"
            size="sm"
            busy={send.isPending}
            icon={<Send className="size-3.5" />}
            onClick={() => send.mutate()}
          >
            {t("send")}
          </Button>
        ) : null}
        {draft.status === "ready_to_publish" ? (
          <Button variant="secondary" size="sm" busy={takeBack.isPending} onClick={() => takeBack.mutate()}>
            {t("takeBack")}
          </Button>
        ) : null}
        {summary.can_approve ? (
          <Button
            variant="primary"
            size="sm"
            busy={decide.isPending}
            icon={<ShieldCheck className="size-3.5" />}
            onClick={() => decide.mutate()}
          >
            {t("approve")}
          </Button>
        ) : null}
        {draft.status !== "archived" && draft.status !== "ready_to_publish" ? (
          <Button variant="ghost" size="sm" busy={retire.isPending} onClick={() => retire.mutate()}>
            {t("archive")}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

/** What is missing, and why each one matters. Straight from the backend, in its words. */
function Gaps({ gaps }: { gaps: SkillGap[] }) {
  const t = useTranslations("factory");
  if (gaps.length === 0) return null;

  return (
    <div className="space-y-1.5 rounded-md border border-approval bg-approval-soft p-2.5">
      <p className="text-xs font-medium">{t("stillNeeded", { count: gaps.length })}</p>
      <ul className="space-y-1 text-xs">
        {gaps.map((gap) => (
          <li key={gap.field}>{gap.remedy}</li>
        ))}
      </ul>
    </div>
  );
}
