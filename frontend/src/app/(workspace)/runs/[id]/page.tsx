"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";

import { fetchRunEvidence, type RunEvidence } from "@/lib/api/runs";
import { useSession } from "@/lib/auth/use-session";
import { contextFor, formatDateTimeWithZone } from "@/lib/format";
import { Alert, Badge, Button, Card, CardBody, CardHeader, QueryStates } from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * A run's evidence — Gate 7.6's screen.
 *
 * §17's runtime tables answer four questions between them, and until now a person had to know
 * which table held which and join them by eye. This is the account: what ran, against which
 * published version, on whose instruction; what happened at each step and how many attempts it
 * took; who decided what and why; and what came out.
 *
 * ## Nothing on this page is computed
 *
 * Every figure is a count of rows the server returned. There is no percentage of completion — a
 * percentage of steps implies each one is the same size, and they are not — no duration a
 * subtraction invented, and no status word this screen chose. `CLAUDE.md`'s first frontend rule is
 * that a value the backend did not return is never displayed, and evidence is the one screen where
 * that is not a style preference: a fabricated number here is a fabricated record.
 *
 * ## What it says it cannot show
 *
 * Tool calls have no producer until Gate 8 wires the integrations, so the bundle carries
 * `tool_calls_available: false` and this page prints that sentence rather than an empty list. *"No
 * tools were used"* and *"this cannot be recorded yet"* are different claims and only the second
 * is true today.
 */
export default function RunEvidencePage() {
  const t = useTranslations("runs");
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { user } = useSession();
  const format = contextFor(user?.timezone);

  const evidence = useQuery({
    queryKey: ["run-evidence", id],
    queryFn: ({ signal }) => fetchRunEvidence(id, signal),
  });

  return (
    <AppShell
      title={t("evidenceTitle")}
      breadcrumb={[{ label: t("backToDashboard"), href: "/dashboard" }]}
    >
      <QueryStates
        isPending={evidence.isPending}
        error={evidence.error}
        onRetry={() => void evidence.refetch()}
      >
        {evidence.data ? <Evidence document={evidence.data} format={format} /> : null}
      </QueryStates>
    </AppShell>
  );
}

/*  Every instant on this page names its timezone.

    `UI_SPEC.md:271` asks for it everywhere, and on evidence it is not a nicety: *"approved at
    09:14"* is not a fact until it says whose nine o'clock. `formatDateTime` deliberately is not
    used here — its own docstring claims to name the zone and it does not, which is a separate
    defect recorded in the audit register. */
function Evidence({
  document,
  format,
}: {
  document: RunEvidence;
  format: ReturnType<typeof contextFor>;
}) {
  const t = useTranslations("runs");
  const { run, steps, events, tasks, approvals, outputs, model_calls: calls } = document;
  const when = (value: string) => formatDateTimeWithZone(value, format);

  /*  The document itself, as the file it already is.

      "Exportable" is the gate's own word, and the honest export is the record the server
      assembled — not a rendering of it. A PDF of this page would be a second format to keep
      faithful, and the first time the two disagreed the pretty one would be the one somebody
      brought to a meeting. */
  const download = () => {
    const blob = new Blob([JSON.stringify(document, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = window.document.createElement("a");
    link.href = url;
    link.download = `run-${run.id}-evidence.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={run.job_name ?? t("unnamedJob")}
          description={t("versionAndTrigger", {
            version: run.job_version_no ?? "?",
            trigger: t(`trigger.${run.trigger}`),
          })}
          action={
            <div className="flex shrink-0 items-center gap-2">
              <Badge tone={run.state === "failed" ? "danger" : "neutral"}>
                {t(`state.${run.state}`)}
              </Badge>
              <Button
                size="sm"
                variant="secondary"
                icon={<Download className="size-3.5" />}
                onClick={download}
              >
                {t("download")}
              </Button>
            </div>
          }
        />
        <CardBody>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Fact label={t("startedBy")} value={run.started_by} />
            <Fact
              label={t("startedAt")}
              value={run.started_at ? when(run.started_at) : null}
            />
            <Fact
              label={t("finishedAt")}
              value={run.finished_at ? when(run.finished_at) : null}
            />
            {/*  Two counts, never a percentage: a percentage of steps implies each one is the
                same size, and they are not. */}
            <Fact
              label={t("stepsLabel")}
              value={t("stepsDone", {
                done: steps.filter((step) => step.state === "succeeded").length,
                total: steps.length,
              })}
            />
          </dl>
          {run.failure_detail ? (
            <Alert tone="danger" title={t("failed")} className="mt-4">
              {run.failure_detail}
            </Alert>
          ) : null}
        </CardBody>
      </Card>

      {/* ── what it did ──────────────────────────────────────────────────────────────── */}
      <Section title={t("steps")} count={steps.length} empty={t("noSteps")}>
        <ol className="space-y-2">
          {steps.map((step) => (
            <li
              key={step.id}
              className="rounded-md border border-border bg-card p-3 text-sm"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium">
                  {step.position}. {step.title}
                </span>
                <span className="flex items-center gap-1.5">
                  <Badge tone="neutral">{t(`mode.${step.mode}`)}</Badge>
                  <Badge tone={step.state === "failed" ? "danger" : "neutral"}>
                    {t(`stepState.${step.state}`)}
                  </Badge>
                  {/*  Attempts are on the record. A retry that left no trace would make a run
                      that succeeded on the third try look like one that succeeded. */}
                  {step.attempt > 1 ? (
                    <Badge tone="approval">{t("attempts", { count: step.attempt })}</Badge>
                  ) : null}
                </span>
              </div>
              {step.failure_detail ? (
                <p className="mt-1 text-danger">{step.failure_detail}</p>
              ) : null}
              {step.result ? (
                <pre className="mt-2 overflow-x-auto rounded bg-muted/50 p-2 text-xs">
                  {JSON.stringify(step.result, null, 2)}
                </pre>
              ) : null}
            </li>
          ))}
        </ol>
      </Section>

      {/* ── what it produced ─────────────────────────────────────────────────────────── */}
      <Section title={t("outputs")} count={outputs.length} empty={t("noOutputs")}>
        <ul className="space-y-2">
          {outputs.map((output) => (
            <li
              key={output.position}
              className="rounded-md border border-border bg-card p-3 text-sm"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                {/*  The name the published version gave it — Form 3's `Output` column. */}
                <span className="font-medium">{output.name}</span>
                {output.destination ? (
                  <span className="text-xs text-muted-foreground">
                    {t("destination", { where: output.destination })}
                  </span>
                ) : null}
              </div>
              {output.value_text ? (
                <p className="mt-1 whitespace-pre-wrap">{output.value_text}</p>
              ) : null}
              {output.file_id ? (
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {t("producedFile", { id: output.file_id })}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>

      {/* ── who decided ──────────────────────────────────────────────────────────────── */}
      <Section title={t("decisions")} count={tasks.length} empty={t("noTasks")}>
        <ul className="space-y-2">
          {tasks.map((task) => {
            const decision = approvals.find((row) => row.task_id === task.id);
            return (
              <li
                key={task.id}
                className="rounded-md border border-border bg-card p-3 text-sm"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{task.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {task.completed_by
                      ? t("completedBy", {
                          who: task.completed_by,
                          when: task.completed_at
                            ? when(task.completed_at)
                            : "—",
                        })
                      : t("assignedTo", { who: task.assignee ?? t("nobody") })}
                  </span>
                </div>
                {task.outcome_note ? (
                  <p className="mt-1 whitespace-pre-wrap">{task.outcome_note}</p>
                ) : null}
                {decision ? (
                  <p className="mt-1 text-xs">
                    {/*  The reason, always. A decision with no reason is a signature nobody can
                        question, which is what separation of duty exists to prevent. */}
                    {t("decidedBy", {
                      state: decision.state,
                      who: decision.decided_by ?? t("nobody"),
                    })}
                    {decision.reason ? ` — ${decision.reason}` : ""}
                  </p>
                ) : null}
                {task.evidence_file_ids.length > 0 ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("attachedFiles", { count: task.evidence_file_ids.length })}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      </Section>

      {/* ── what it asked a model ────────────────────────────────────────────────────── */}
      <Section title={t("modelCalls")} count={calls.length} empty={t("noModelCalls")}>
        <ul className="space-y-2">
          {calls.map((call, index) => (
            <li
              key={index}
              className="rounded-md border border-border bg-card p-3 text-sm"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium">{call.model}</span>
                <Badge tone={call.outcome === "completed" ? "neutral" : "danger"}>
                  {t(`callOutcome.${call.outcome}`)}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {call.outcome === "completed"
                  ? t("callUsage", {
                      provider: call.provider,
                      input: call.input_tokens ?? 0,
                      output: call.output_tokens ?? 0,
                      ms: call.latency_ms ?? 0,
                    })
                  : (call.detail ?? "")}
              </p>
            </li>
          ))}
        </ul>
      </Section>

      {/* ── what cannot be shown yet ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader title={t("toolCalls")} />
        <CardBody>
          {document.tool_calls_available ? (
            <p className="text-sm text-muted-foreground">
              {t("toolCallsCount", { count: document.tool_calls.length })}
            </p>
          ) : (
            //  Not an empty list. "No tools were used" is a claim about the run; "this cannot be
            //  recorded yet" is a claim about the system, and it is the true one today.
            <Alert tone="info">{t("toolCallsUnavailable")}</Alert>
          )}
        </CardBody>
      </Card>

      {/* ── what happened, in order ──────────────────────────────────────────────────── */}
      <Section title={t("events")} count={events.length} empty={t("noEvents")}>
        <ol className="space-y-1">
          {events.map((event, index) => (
            <li key={index} className="flex flex-wrap gap-x-3 text-xs">
              <span className="w-40 shrink-0 font-mono text-muted-foreground">
                {event.occurred_at ? when(event.occurred_at) : "—"}
              </span>
              <span className="font-medium">{event.kind}</span>
              {Object.keys(event.detail ?? {}).length > 0 ? (
                <span className="text-muted-foreground">
                  {JSON.stringify(event.detail)}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </Section>
    </div>
  );
}

/** One labelled fact. Nothing derived — every value came from the response. */
function Fact({ label, value }: { label: string; value: string | null }) {
  const t = useTranslations("runs");
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm">{value ?? t("notRecorded")}</dd>
    </div>
  );
}

/**
 * A section with its own count, and its own empty state.
 *
 * The count is in the heading because *"three outputs"* and *"no outputs"* are both facts a reader
 * needs, and a section that simply vanishes when empty leaves them wondering whether it was
 * checked.
 */
function Section({
  title,
  count,
  empty,
  children,
}: {
  title: string;
  count: number;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader title={title} action={<Badge tone="neutral">{count}</Badge>} />
      <CardBody>
        {count === 0 ? <p className="text-sm text-muted-foreground">{empty}</p> : children}
      </CardBody>
    </Card>
  );
}
