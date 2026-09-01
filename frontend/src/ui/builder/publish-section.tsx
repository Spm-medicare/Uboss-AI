"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  CheckCircle2,
  Send,
  ShieldCheck,
  Undo2,
  User,
  Users,
} from "lucide-react";
import { useTranslations } from "next-intl";

import {
  fetchPublishSummary,
  fetchVersions,
  publishObjective,
  submitObjective,
  withdrawObjective,
} from "@/lib/api/objective-publish";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTime } from "@/lib/format";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { QueryStates } from "@/ui/states";

/**
 * The publish summary and the approval route — PLAN §7's publish screen.
 *
 * *"Publish shows owners, steps, schedules, permissions, cost, warnings and approval route.
 * Approval creates immutable ObjectiveVersion."*
 *
 * Three things this screen is careful about:
 *
 * **Whose turn it is comes from the server.** `next_action` is a sentence the API writes. Two
 * screens each inferring it from status and identity is how an approval queue ends up with both
 * people waiting for the other.
 *
 * **Warnings are shown and never block.** Each is a choice an organisation may make on purpose;
 * the product's job is to be sure the approver saw it, not to overrule them.
 *
 * **Cost is what the analysis actually spent.** Real tokens from the run that produced this plan,
 * or nothing at all. An estimate printed here is a number somebody would quote.
 */
export function PublishSection({
  objectiveId,
  editable,
  timeZone,
  onChanged,
}: {
  objectiveId: string;
  editable: boolean;
  timeZone: string | undefined;
  /** Submitting and approving both move the status, so the form above re-reads. */
  onChanged: () => void;
}) {
  const t = useTranslations("publish");
  const queryClient = useQueryClient();
  const format = contextFor(timeZone);

  const summary = useQuery({
    queryKey: ["objective", objectiveId, "publish"],
    queryFn: ({ signal }) => fetchPublishSummary(objectiveId, signal),
  });
  const versions = useQuery({
    queryKey: ["objective", objectiveId, "versions"],
    queryFn: ({ signal }) => fetchVersions(objectiveId, signal),
  });

  function reload() {
    void queryClient.invalidateQueries({ queryKey: ["objective", objectiveId] });
    onChanged();
  }

  const submit = useMutation({
    mutationFn: (version: number) => submitObjective(objectiveId, version),
    onSuccess: reload,
  });
  const withdraw = useMutation({
    mutationFn: (version: number) => withdrawObjective(objectiveId, version),
    onSuccess: reload,
  });
  const approve = useMutation({
    mutationFn: (version: number) => publishObjective(objectiveId, version),
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
            {/*  Whose turn, in the server's words. First, because it is the only thing most
                people opening this section need. */}
            <div className="rounded-lg border border-border bg-muted/40 px-4 py-3">
              <p className="text-sm">{summary.data.next_action}</p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Facts
                title={t("who")}
                rows={[
                  [t("owner"), summary.data.owner_name],
                  [t("approver"), summary.data.approver_name],
                  [t("submittedBy"), summary.data.submitted_by_name],
                  [t("department"), summary.data.department],
                ]}
              />

              <div className="rounded-lg border border-border bg-card p-4">
                <p className="text-sm font-semibold">{t("theWork")}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <KindCount
                    icon={User}
                    tone="human"
                    label={t("humanSteps", { count: summary.data.human_steps })}
                    count={summary.data.human_steps}
                  />
                  <KindCount
                    icon={Bot}
                    tone="ai"
                    label={t("agentSteps", { count: summary.data.agent_steps })}
                    count={summary.data.agent_steps}
                  />
                  <KindCount
                    icon={Users}
                    tone="hybrid"
                    label={t("hybridSteps", { count: summary.data.hybrid_steps })}
                    count={summary.data.hybrid_steps}
                  />
                  <KindCount
                    icon={ShieldCheck}
                    tone="approval"
                    label={t("approvalSteps", { count: summary.data.approval_steps })}
                    count={summary.data.approval_steps}
                  />
                </div>
                <p className="mt-3 border-t border-border pt-2 text-xs text-muted-foreground">
                  {t("provenance", {
                    proposed: summary.data.ai_proposed,
                    edited: summary.data.ai_edited,
                    added: summary.data.human_added,
                  })}
                </p>
                {/*  What it cost, from the run that produced this plan. Nothing at all when no
                    analysis has run — never an estimate. */}
                {summary.data.analysis_model ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("cost", {
                      model: summary.data.analysis_model,
                      tokens: summary.data.analysis_tokens,
                    })}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">{t("noAnalysisCost")}</p>
                )}
              </div>
            </div>

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
              {/*  Disabled with the reason beside it, not removed.

                  A control that vanishes leaves somebody looking for it; the server already
                  computes exactly why it cannot be pressed and returns it as `next_action`, and
                  that sentence is more useful than an empty space. Hidden entirely only once the
                  thing has been submitted, when the question is no longer "why can I not send
                  this". */}
              {summary.data.status === "draft" ||
              summary.data.status === "needs_review" ? (
                <>
                  <Button
                    variant="primary"
                    icon={<Send className="size-4" />}
                    busy={submit.isPending}
                    disabled={!summary.data.can_submit}
                    onClick={() => submit.mutate(summary.data.version)}
                  >
                    {t("sendForApproval")}
                  </Button>
                  {!summary.data.can_submit && summary.data.next_action ? (
                    <span className="text-xs text-muted-foreground">
                      {t("cannotSubmit", { reason: summary.data.next_action })}
                    </span>
                  ) : null}
                </>
              ) : null}

              {summary.data.status === "ready_to_publish" && editable === false ? (
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

      {/*  A failed versions lookup used to render as nothing at all, which on this panel reads as
          *never published* — a request that failed, reported as a fact about the record. Said
          plainly instead, with the way to try again. */}
      {versions.error ? (
        <Alert tone="danger" title={t("versionsFailedTitle")}>
          {t("versionsFailedBody")}{" "}
          <button
            type="button"
            className="underline underline-offset-4"
            onClick={() => void versions.refetch()}
          >
            {t("versionsRetry")}
          </button>
        </Alert>
      ) : null}

      {versions.data && versions.data.length > 0 ? (
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-semibold">{t("published")}</p>
          <ul className="mt-2 divide-y divide-border">
            {versions.data.map((version) => (
              <li key={version.id} className="flex flex-wrap items-baseline gap-x-3 py-2">
                <Badge tone="success">{t("versionNo", { no: version.version_no })}</Badge>
                <span className="text-sm">{version.title}</span>
                <span className="text-xs text-muted-foreground">
                  {t("approvedBy", { name: version.approved_by_name ?? "—" })} ·{" "}
                  {formatDateTime(version.published_at, format)}
                </span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {t("stepsInVersion", { count: version.step_count ?? 0 })}
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

function Facts({
  title,
  rows,
}: {
  title: string;
  rows: [string, string | null | undefined][];
}) {
  const t = useTranslations("publish");
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-sm font-semibold">{title}</p>
      <dl className="mt-2 space-y-1.5">
        {rows.map(([label, value]) => (
          <div key={label} className="flex gap-3 text-sm">
            <dt className="w-28 shrink-0 text-muted-foreground">{label}</dt>
            <dd className={cn("min-w-0", !value && "text-muted-foreground")}>
              {value || t("notSet")}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** A count with its kind's colour. Zero is drawn muted rather than hidden — absence is a fact. */
function KindCount({
  icon: Icon,
  tone,
  label,
  count,
}: {
  icon: typeof User;
  tone: "human" | "ai" | "hybrid" | "approval";
  label: string;
  count: number;
}) {
  return (
    <Badge tone={count > 0 ? tone : "neutral"} icon={<Icon className="size-3" />}>
      {label}
    </Badge>
  );
}
