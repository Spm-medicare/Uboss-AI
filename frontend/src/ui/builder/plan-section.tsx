"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { StepKind } from "@/lib/api/contract";
import {
  addStep,
  analyse,
  deleteStep,
  duplicateStep,
  fetchPlan,
  mergeStep,
  reorderPlan,
  setDependencies,
  updateStep,
  type Plan,
} from "@/lib/api/objective-plan";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { QueryStates } from "@/ui/states";
import { AnalysisTimeline } from "@/ui/builder/analysis-timeline";
import {
  OutputBlock,
  OutputEmpty,
  OutputPanel,
  OutputToggle,
} from "@/ui/builder/output-panel";
import { PlanStep } from "@/ui/builder/plan-step";

/**
 * The proposed plan, and everything a person does to it.
 *
 * PLAN §6's journey runs *approve AI analysis → real analysis timeline → editable generated
 * output*, and this is the last two of those three. The timeline is above the plan rather than
 * hidden behind a link, because after a failure it is the part worth reading.
 *
 * **Every edit goes to the server and the plan is re-read.** No optimistic update: positions,
 * versions and the `edited` flag are all decided server-side, and a local guess at any of them
 * would be wrong the first time two people worked on one objective. A plan is edited in
 * considered steps, not typed into, so the round trip costs nothing a person notices.
 */
export function PlanSection({
  objectiveId,
  objectiveVersion,
  editable,
  timeZone,
  onReloadObjective,
  outputOpen,
  onOutputOpenChange,
}: {
  objectiveId: string;
  objectiveVersion: number;
  editable: boolean;
  timeZone: string | undefined;
  /** The analysis moves the objective's status, so the form above has to re-read it. */
  onReloadObjective: () => void;
  /**
   * The drawer, controlled by the page.
   *
   * Lifted out of this component because it is opened from two places — a run, and the pinned
   * guidance panel's own toggle — and two pieces of state for one drawer is a drawer that says
   * "hide" while it is shut.
   */
  outputOpen: boolean;
  onOutputOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("plan");
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);


  const plan = useQuery({
    queryKey: ["objective", objectiveId, "plan"],
    queryFn: ({ signal }) => fetchPlan(objectiveId, signal),
  });

  function reload() {
    void queryClient.invalidateQueries({
      queryKey: ["objective", objectiveId, "plan"],
    });
  }

  /** Every mutation does the same three things, so they are written once. */
  function act<T>(run: () => Promise<T>) {
    setFailure(null);
    run()
      .then(() => reload())
      .catch((error: unknown) =>
        setFailure(error instanceof Error ? error.message : String(error)),
      );
  }

  const analysing = useMutation({
    mutationFn: () => analyse(objectiveId, objectiveVersion),
    onSuccess: () => {
      reload();
      onReloadObjective();
      //  Running is the moment somebody wants to see what came back, so the run opens it. Nothing
      //  else does: a drawer that opened on load would cover the form for somebody who came to
      //  edit the plan rather than to re-run it.
      onOutputOpenChange(true);
    },
    onError: (error) => setFailure(error.message),
  });

  return (
    <div className="space-y-4">
      <QueryStates
        isPending={plan.isPending}
        error={plan.error}
        onRetry={() => void plan.refetch()}
      >
        {plan.data ? (
          <>
            {/*  The toggle sits with the run, not in the page chrome, so "show me what that
                produced" is next to the thing that produced it. */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">{t("timelineTitle")}</p>
              <OutputToggle
                tone="plain"
                open={outputOpen}
                onToggle={() => onOutputOpenChange(!outputOpen)}
                {...(plan.data.analysis ? { count: 1 } : {})}
              />
            </div>

            {/*  A failure stays in the form. It is the reason nothing happened, and a reason
                behind a toggle is somebody pressing the button again and learning nothing. */}
            {failure ? <Alert tone="danger">{failure}</Alert> : null}
            {plan.data.analysis?.status === "failed" ? (
              <Alert tone="danger">{plan.data.analysis.failure_detail}</Alert>
            ) : null}

            <OutputPanel
              open={outputOpen}
              onClose={() => onOutputOpenChange(false)}
              label={t("outputLabel")}
              title={t("outputTitle")}
            >
              {plan.data.analysis ? (
                <>
                  <OutputBlock title={t("timelineTitle")}>
                    <AnalysisTimeline analysis={plan.data.analysis} timeZone={timeZone} />
                    {plan.data.analysis.model ? (
                      //  Which model, and what it cost. Said plainly rather than buried:
                      //  somebody paying for this is entitled to see it on the screen that
                      //  spent it.
                      <p className="mt-3 text-xs text-muted-foreground">
                        {t("ranOn", {
                          model: plan.data.analysis.model,
                          tokens:
                            (plan.data.analysis.input_tokens ?? 0) +
                            (plan.data.analysis.output_tokens ?? 0),
                        })}
                      </p>
                    ) : null}
                    {plan.data.analysis.note ? (
                      <Alert tone="info" className="mt-3" title={t("modelNote")}>
                        {plan.data.analysis.note}
                      </Alert>
                    ) : null}
                  </OutputBlock>

                  {plan.data.steps.length > 0 ? (
                    <OutputBlock title={t("comparisonTitle")}>
                      <Comparison plan={plan.data} />
                    </OutputBlock>
                  ) : null}
                </>
              ) : (
                <OutputEmpty>{t("outputEmpty")}</OutputEmpty>
              )}
            </OutputPanel>

            {plan.data.steps.length === 0 ? (
              <NoPlanYet
                neverAnalysed={plan.data.never_analysed}
                editable={editable}
                busy={analysing.isPending}
                onAnalyse={() => analysing.mutate()}
              />
            ) : (
              <>
                <ul className="space-y-2">
                  {plan.data.steps.map((step, index) => (
                    <PlanStep
                      key={step.id}
                      step={step}
                      index={index}
                      total={plan.data.steps.length}
                      steps={plan.data.steps}
                      disabled={!editable}
                      onChange={(changes) =>
                        act(() =>
                          updateStep(objectiveId, step.id, {
                            ...changes,
                            expected_version: step.version,
                          }),
                        )
                      }
                      onRemove={() =>
                        act(() => deleteStep(objectiveId, step.id, step.version))
                      }
                      onDuplicate={() => act(() => duplicateStep(objectiveId, step.id))}
                      onMerge={(into) => act(() => mergeStep(objectiveId, step.id, into))}
                      onDependencies={(dependsOn) =>
                        act(() => setDependencies(objectiveId, step.id, dependsOn))
                      }
                      onMove={(direction) => {
                        const target = index + direction;
                        if (target < 0 || target >= plan.data.steps.length) return;
                        const order = plan.data.steps.map((item) => item.id);
                        const moved = order[index]!;
                        order[index] = order[target]!;
                        order[target] = moved;
                        act(() => reorderPlan(objectiveId, order));
                      }}
                    />
                  ))}
                </ul>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    disabled={!editable}
                    icon={<Plus className="size-4" />}
                    onClick={() =>
                      act(() =>
                        addStep(objectiveId, {
                          kind: "human" as StepKind,
                          title: t("newStepTitle"),
                        }),
                      )
                    }
                  >
                    {t("addStep")}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={!editable}
                    busy={analysing.isPending}
                    icon={<RefreshCw className="size-4" />}
                    onClick={() => analysing.mutate()}
                  >
                    {t("analyseAgain")}
                  </Button>
                  {/*  Said out loud, because it is the surprising part: a re-analysis replaces
                      the plan, and somebody who has spent an hour editing needs to know that
                      before they press it, not after. */}
                  <span className="text-xs text-muted-foreground">{t("rerunReplaces")}</span>
                </div>
              </>
            )}
          </>
        ) : null}
      </QueryStates>
    </div>
  );
}

/**
 * PLAN §7's *"compare AI/human changes"*, as three numbers.
 *
 * Counts, never a percentage or a score. "The model got 80% right" would need a definition of
 * right that nobody has agreed, and it would be read as one.
 */
function Comparison({ plan }: { plan: Plan }) {
  const t = useTranslations("plan");
  const proposed = plan.ai_steps ?? 0;
  const edited = plan.edited_ai_steps ?? 0;
  const mine = plan.human_steps ?? 0;

  if (proposed === 0 && mine === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {proposed > 0 ? <Badge tone="ai">{t("proposedCount", { count: proposed })}</Badge> : null}
      {edited > 0 ? <Badge tone="approval">{t("editedCount", { count: edited })}</Badge> : null}
      {mine > 0 ? <Badge tone="human">{t("yoursCount", { count: mine })}</Badge> : null}
    </div>
  );
}

/**
 * No plan yet.
 *
 * `never_analysed` separates "nothing has been asked for" from "a plan somebody emptied". They
 * look identical and need different words — one offers the analysis, the other does not pretend
 * the analysis never happened.
 */
function NoPlanYet({
  neverAnalysed,
  editable,
  busy,
  onAnalyse,
}: {
  neverAnalysed: boolean;
  editable: boolean;
  busy: boolean;
  onAnalyse: () => void;
}) {
  const t = useTranslations("plan");

  return (
    <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center">
      <Sparkles aria-hidden className="mx-auto size-7 text-ai" />
      <p className="mt-3 text-sm font-medium">
        {neverAnalysed ? t("emptyTitle") : t("emptiedTitle")}
      </p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
        {neverAnalysed ? t("emptyBody") : t("emptiedBody")}
      </p>
      {editable ? (
        <Button
          variant="primary"
          className="mt-4"
          busy={busy}
          icon={<Sparkles className="size-4" />}
          onClick={onAnalyse}
        >
          {neverAnalysed ? t("analyse") : t("analyseAgain")}
        </Button>
      ) : null}
    </div>
  );
}
