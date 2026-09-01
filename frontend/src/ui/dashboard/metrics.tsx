"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckSquare,
  Inbox,
  Play,
  ShieldCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ReactNode } from "react";

import { fetchRuns } from "@/lib/api/runs";
import { fetchTaskCounts } from "@/lib/api/tasks";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTime } from "@/lib/format";
import { Badge, QueryStates } from "@/ui";

/**
 * §4's metrics — *"Pending and overdue tasks. Approvals and inputs waiting for the user.
 * Running, scheduled and failed Agents."*
 *
 * These could not exist when the Dashboard was first built: there were no tasks, no approvals
 * and no runs, so the screen deliberately showed none rather than a wall of zeros. Gates 7.1
 * to 7.5 produced all three, so the numbers are now real — and every one of them comes from an
 * endpoint, never from arithmetic on this page.
 *
 * §4 also says *"Every metric is clickable, defined and timestamped."* So each tile is a link to
 * the screen that explains it, each carries a one-line definition rather than a bare noun, and
 * the runs list shows when each one happened.
 *
 * **A failed request draws a failure.** Not a zero — "nothing is waiting on you" and "we could
 * not find out" are opposite statements and must never look alike.
 */
export function DashboardMetrics({ timeZone }: { timeZone: string | undefined }) {
  const t = useTranslations("dashboard");
  const format = contextFor(timeZone);

  const tasks = useQuery({
    queryKey: ["tasks", "counts"],
    queryFn: ({ signal }) => fetchTaskCounts(signal),
  });
  const runs = useQuery({
    queryKey: ["runs", "recent"],
    queryFn: ({ signal }) => fetchRuns(8, signal),
  });

  //  Counted from the page of runs the API returned, and labelled as such — `recentLabel` says
  //  "of the last 8". A tile that said "2 failed" from a page of eight would imply two in total,
  //  which is a different and unverified claim.
  const recent = runs.data ?? [];
  const running = recent.filter(
    (run) => run.state === "running" || run.state === "pending",
  ).length;
  const failed = recent.filter((run) => run.state === "failed").length;

  return (
    <div className="space-y-6">
      <section aria-labelledby="waiting-heading">
        <h3 id="waiting-heading" className="text-sm font-semibold">
          {t("waitingHeading")}
        </h3>
        <QueryStates
          isPending={tasks.isPending}
          error={tasks.error}
          onRetry={() => void tasks.refetch()}
        >
          <div className="mt-3 grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,15rem),1fr))]">
            <Metric
              href="/todo?tab=mine"
              icon={<CheckSquare className="size-4" />}
              label={t("metric.tasks")}
              hint={t("metricHint.tasks")}
              value={tasks.data?.mine_open ?? 0}
              tone={(tasks.data?.mine_open ?? 0) > 0 ? "primary" : "quiet"}
            />
            <Metric
              href="/todo?tab=approvals"
              icon={<ShieldCheck className="size-4" />}
              label={t("metric.approvals")}
              hint={t("metricHint.approvals")}
              value={tasks.data?.approvals ?? 0}
              tone={(tasks.data?.approvals ?? 0) > 0 ? "approval" : "quiet"}
            />
            <Metric
              href="/todo?tab=input"
              icon={<Inbox className="size-4" />}
              label={t("metric.input")}
              hint={t("metricHint.input")}
              value={tasks.data?.input_requested ?? 0}
              tone={(tasks.data?.input_requested ?? 0) > 0 ? "primary" : "quiet"}
            />
            <Metric
              href="/todo?tab=following"
              icon={<Play className="size-4" />}
              label={t("metric.following")}
              hint={t("metricHint.following")}
              value={tasks.data?.following_open ?? 0}
              tone="quiet"
            />
          </div>
        </QueryStates>
      </section>

      <section aria-labelledby="runs-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="runs-heading" className="text-sm font-semibold">
            {t("runsHeading")}
          </h3>
          {recent.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              {t("recentLabel", { count: recent.length })}
            </p>
          ) : null}
        </div>

        <QueryStates
          isPending={runs.isPending}
          error={runs.error}
          isEmpty={recent.length === 0}
          emptyTitle={t("noRuns")}
          emptyDescription={t("noRunsWhy")}
          onRetry={() => void runs.refetch()}
        >
          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
            <div className="grid content-start gap-3 sm:grid-cols-2 lg:grid-cols-1">
              <Metric
                href="/todo?tab=following"
                icon={<Play className="size-4" />}
                label={t("metric.running")}
                hint={t("metricHint.running")}
                value={running}
                tone={running > 0 ? "primary" : "quiet"}
              />
              <Metric
                href="/todo?tab=following"
                icon={<AlertTriangle className="size-4" />}
                label={t("metric.failed")}
                hint={t("metricHint.failed")}
                value={failed}
                tone={failed > 0 ? "danger" : "quiet"}
              />
            </div>

            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <ul className="divide-y divide-border">
                {recent.map((run) => (
                  <li
                    key={run.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5"
                  >
                    <Badge tone={RUN_TONE[run.state] ?? "neutral"}>
                      {t(`runStates.${run.state}`)}
                    </Badge>
                    {/*  The way to a run's evidence. Until 7.6 there was no screen to link to,
                        so a run on this list was a fact with nowhere to go — somebody who saw a
                        failure here had to read the database to find out what happened. */}
                    <Link
                      href={`/runs/${run.id}`}
                      className="min-w-0 max-w-[16rem] truncate text-sm font-medium underline-offset-4 hover:underline"
                    >
                      {run.job_name ?? t("unnamedJob")}
                    </Link>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {t("steps", {
                        done: run.steps_done,
                        total: run.steps_total,
                      })}
                    </span>
                    {run.failure_detail ? (
                      <span className="min-w-0 flex-1 truncate text-xs text-danger">
                        {run.failure_detail}
                      </span>
                    ) : null}
                    {/*  §4: every metric is *timestamped*. The instant a run started, or that it
                        has not — never a guess at one. */}
                    <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">
                      {run.started_at
                        ? formatDateTime(run.started_at, format)
                        : t("notStarted")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </QueryStates>
      </section>
    </div>
  );
}

const RUN_TONE: Record<string, "neutral" | "success" | "danger" | "ai" | "approval"> = {
  pending: "neutral",
  running: "ai",
  waiting: "approval",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
};

/**
 * One number, its definition, and the screen that explains it.
 *
 * **The number carries the tone.** A row of identical white rectangles has to be read digit by
 * digit; a row where the two cards with work on them are visibly warmer can be read at a glance,
 * which is the whole job of §4's *"show what needs attention now"*.
 *
 * A card at zero is deliberately plain — quiet, not absent. It is a real answer and it stays on
 * screen, because a metric that disappeared when it hit zero would leave somebody wondering
 * whether it was zero or broken.
 *
 * The count is always rendered. What is **never** rendered is a zero standing in for a failed
 * request; that is `QueryStates`' job above, and the distinction is the reason this component
 * takes a number rather than fetching one.
 */
function Metric({
  href,
  icon,
  label,
  hint,
  value,
  tone,
}: {
  href: string;
  icon: ReactNode;
  label: string;
  hint: string;
  value: number;
  tone: "primary" | "approval" | "danger" | "quiet";
}) {
  const live = tone !== "quiet" && value > 0;

  return (
    <Link
      href={href}
      className={cn(
        "group relative flex h-full flex-col gap-2 overflow-hidden rounded-xl border p-4",
        "transition-all duration-150 motion-reduce:transition-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        live
          ? "border-transparent shadow-sm hover:shadow-md"
          : "border-border bg-card hover:bg-accent",
        live && tone === "primary" && "bg-primary/[0.07]",
        live && tone === "approval" && "bg-approval-soft",
        live && tone === "danger" && "bg-danger-soft",
      )}
    >
      {/*  A rail in the tone, so the card is identifiable without relying on the fill — which a
          monochrome display and a person with low vision both lose. */}
      {live ? (
        <span
          aria-hidden
          className={cn(
            "absolute inset-y-0 left-0 w-1",
            tone === "primary" && "bg-primary",
            tone === "approval" && "bg-approval",
            tone === "danger" && "bg-danger",
          )}
        />
      ) : null}

      <div className="flex items-center justify-between gap-2">
        <span
          aria-hidden
          className={cn(
            "grid size-8 place-items-center rounded-lg",
            tone === "primary" && (live ? "bg-primary text-white" : "bg-primary/10 text-primary"),
            tone === "approval" &&
              (live ? "bg-approval text-white" : "bg-approval-soft text-approval"),
            tone === "danger" && (live ? "bg-danger text-white" : "bg-danger-soft text-danger"),
            tone === "quiet" && "bg-muted text-muted-foreground",
          )}
        >
          {icon}
        </span>
        <ArrowUpRight
          aria-hidden
          className={cn(
            "size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity duration-150",
            "group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none",
          )}
        />
      </div>

      <div>
        <p
          className={cn(
            "text-[2rem] font-semibold leading-none tabular-nums",
            live && tone === "primary" && "text-primary",
            live && tone === "approval" && "text-approval",
            live && tone === "danger" && "text-danger",
            !live && "text-foreground",
          )}
        >
          {value}
        </p>
        <p className="mt-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          {label}
        </p>
      </div>

      {/*  §4: every metric is *defined*. A bare "12" invites everybody to guess at what was
          counted, and they guess differently. */}
      <p className="mt-auto text-xs leading-relaxed text-muted-foreground">{hint}</p>
    </Link>
  );
}
