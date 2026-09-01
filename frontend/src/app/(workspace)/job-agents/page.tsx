"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleUserRound,
  Inbox,
  ShieldCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ReactNode } from "react";

import { fetchTaskCounts } from "@/lib/api/tasks";
import { useSession } from "@/lib/auth/use-session";
import { hasAdminWorkspace } from "@/lib/shell/navigation";
import { Card, CardBody, QueryStates } from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";
import { PageHeader } from "@/ui/shell/page-header";

/**
 * Phase 1's first Job Agent surface. Every number is a real governed Task count; company and
 * department roll-ups wait for their scoped aggregation API rather than being simulated here.
 */
export default function JobAgentsPage() {
  const t = useTranslations("jobAgents");
  const { user } = useSession();
  const admin = user ? hasAdminWorkspace(user) : false;
  const counts = useQuery({
    queryKey: ["tasks", "counts"],
    queryFn: ({ signal }) => fetchTaskCounts(signal),
  });

  return (
    <AppShell title={admin ? t("adminTitle") : t("myTitle")}>
      <div className="space-y-7">
        <PageHeader
          title={admin ? t("adminHeading") : t("myHeading")}
          description={admin ? t("adminIntro") : t("myIntro")}
          aside={
            <Link
              href="/todo"
              className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              {t("openQueue")}
              <ArrowRight aria-hidden className="size-4" />
            </Link>
          }
        />

        <QueryStates
          isPending={counts.isPending}
          error={counts.error}
          onRetry={() => void counts.refetch()}
        >
          {counts.data ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Metric icon={<Inbox />} label={t("assigned")} value={counts.data.mine_open} />
              <Metric icon={<ShieldCheck />} label={t("approvals")} value={counts.data.approvals} />
              <Metric icon={<CircleUserRound />} label={t("inputs")} value={counts.data.input_requested} />
              <Metric
                icon={<CheckCircle2 />}
                label={admin ? t("unassigned") : t("following")}
                value={admin ? counts.data.unassigned : counts.data.following_open}
              />
            </div>
          ) : null}
        </QueryStates>

        <Card>
          <CardBody className="p-0">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold">{t("flowTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("flowBody")}</p>
            </div>
            <ol className="grid gap-px bg-border sm:grid-cols-4">
              {[
                ["01", t("flowObjective"), <Bot key="objective" />],
                ["02", t("flowAllocation"), <CircleUserRound key="allocation" />],
                ["03", t("flowWork"), <Inbox key="work" />],
                ["04", t("flowEvidence"), <ShieldCheck key="evidence" />],
              ].map(([number, label, icon]) => (
                <li key={String(number)} className="bg-card px-5 py-5">
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span className="text-xs font-semibold tracking-wider">{number}</span>
                    <span className="[&>svg]:size-4">{icon}</span>
                  </div>
                  <p className="mt-5 text-sm font-medium">{label}</p>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <Card>
      <CardBody className="flex items-center gap-4 p-5">
        <span className="grid size-10 place-items-center rounded-lg bg-primary/10 text-primary [&>svg]:size-4">
          {icon}
        </span>
        <div>
          <p className="text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
          <p className="text-sm text-muted-foreground">{label}</p>
        </div>
      </CardBody>
    </Card>
  );
}
