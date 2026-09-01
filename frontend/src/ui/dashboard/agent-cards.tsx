"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, Target, UserCog, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { fetchAgents } from "@/lib/api/agents";
import { fetchJobs } from "@/lib/api/jobs";
import { fetchObjectives } from "@/lib/api/objectives";
import { fetchSupervisors } from "@/lib/api/supervisors";
import { cn } from "@/lib/cn";
import { contextFor, formatDate } from "@/lib/format";
import { Badge, ErrorState, Skeleton } from "@/ui";
import { toneFor, toneVars } from "@/ui/agent-tone";

/** One row of the card: a record, its state, and when it last changed. */
interface Row {
  id: string;
  name: string;
  status: string;
  updated_at: string;
}

/**
 * The four Agents, each as a card — §3's numbering, §4's *"quick actions that route into the
 * correct Builder"*.
 *
 * **The counts are counted, not claimed.** Each card fetches its own list and derives published
 * and draft from the rows it received. Nothing is estimated, and a card whose request failed says
 * so rather than showing a zero — "you have no Jobs" and "we could not find out" are opposite
 * statements, and only one of them is ever true at a time.
 *
 * **Each card loads independently.** Four separate queries rather than one gate: a slow
 * supervisors endpoint must not hold up the Objectives card, and a broken one must not blank the
 * row. That is why the loading and error states are per card rather than around the section.
 *
 * The three most recently changed records are listed under each count, because *"12 Jobs"* is a
 * number and *"Month end close, changed yesterday"* is somewhere to go.
 */
export function AgentCards({
  timeZone,
  actions,
}: {
  timeZone: string | undefined;
  /** The verbs this session carries. A card whose Builder they cannot open is not shown. */
  actions: readonly string[];
}) {
  const t = useTranslations("dashboard");
  const tNav = useTranslations("nav");
  const format = contextFor(timeZone);

  const objectives = useQuery({
    queryKey: ["objectives", "list"],
    queryFn: ({ signal }) => fetchObjectives({ signal }),
  });
  const jobs = useQuery({
    queryKey: ["jobs", "list"],
    queryFn: ({ signal }) => fetchJobs({ signal }),
  });
  const agents = useQuery({
    queryKey: ["agents", "list"],
    queryFn: ({ signal }) => fetchAgents({ signal }),
  });
  const supervisors = useQuery({
    queryKey: ["supervisors", "list"],
    queryFn: ({ signal }) => fetchSupervisors({ signal }),
  });

  const cards: {
    id: string;
    ordinal: string;
    href: string;
    icon: LucideIcon;
    requires: string;
    isPending: boolean;
    error: Error | null;
    refetch: () => void;
    rows: Row[];
  }[] = [
    {
      id: "objectiveBuilder",
      ordinal: "01",
      href: "/objective-builder",
      icon: Target,
      requires: "edit_draft",
      isPending: objectives.isPending,
      error: objectives.error,
      refetch: () => void objectives.refetch(),
      rows: (objectives.data?.objectives ?? []).map((row) => ({
        id: row.id,
        name: row.title,
        status: row.status,
        updated_at: row.updated_at,
      })),
    },
    {
      id: "jobBuilder",
      ordinal: "02",
      href: "/job-builder",
      icon: Workflow,
      requires: "edit_draft",
      isPending: jobs.isPending,
      error: jobs.error,
      refetch: () => void jobs.refetch(),
      rows: (jobs.data?.jobs ?? []).map((row) => ({
        id: row.id,
        name: row.name,
        status: row.status,
        updated_at: row.updated_at,
      })),
    },
    {
      id: "agentBuilder",
      ordinal: "03",
      href: "/agent-builder",
      icon: Bot,
      requires: "edit_draft",
      isPending: agents.isPending,
      error: agents.error,
      refetch: () => void agents.refetch(),
      rows: (agents.data?.agents ?? []).map((row) => ({
        id: row.id,
        name: row.name,
        status: row.status,
        updated_at: row.updated_at,
      })),
    },
    {
      id: "supervisor",
      ordinal: "04",
      href: "/supervisor",
      icon: UserCog,
      requires: "run",
      isPending: supervisors.isPending,
      error: supervisors.error,
      refetch: () => void supervisors.refetch(),
      rows: (supervisors.data?.supervisors ?? []).map((row) => ({
        id: row.id,
        name: row.name,
        status: row.status,
        updated_at: row.updated_at,
      })),
    },
  ];

  //  Hidden rather than disabled here, unlike the sidebar. The sidebar is a map and an absent
  //  row reads as "no access"; this is a set of shortcuts, and a shortcut somebody cannot use is
  //  simply not a shortcut for them.
  const shown = cards.filter((card) => actions.includes(card.requires));
  if (shown.length === 0) return null;

  return (
    <section aria-labelledby="agents-heading">
      <h3 id="agents-heading" className="text-sm font-semibold">
        {t("agentsHeading")}
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">{t("agentsSubtitle")}</p>

      <ul className="mt-3 grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,17rem),1fr))]">
        {shown.map((card) => {
          const published = card.rows.filter(
            (row) => row.status === "published",
          ).length;
          const drafts = card.rows.filter((row) => row.status === "draft").length;
          const latest = [...card.rows]
            .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
            .slice(0, 3);

          return (
            <li
              key={card.id}
              //  The Agent's own hue — the same one its Builder paints its section bars with, so
              //  the teal card leads to the teal form. Identity, not state: the published/draft
              //  badges below carry the state and keep the semantic colours.
              style={toneVars(toneFor(card.id))}
              className={cn(
                "flex flex-col overflow-hidden rounded-xl border border-border bg-card",
                "border-t-[3px] border-t-[var(--card-accent)]",
              )}
            >
              <Link
                href={card.href}
                className={cn(
                  "group flex items-start gap-3 rounded-t-xl p-4 transition-colors duration-150",
                  "hover:bg-accent motion-reduce:transition-none",
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                )}
              >
                <span
                  aria-hidden
                  className="grid size-9 shrink-0 place-items-center rounded-lg"
                  style={{
                    background: "var(--card-soft)",
                    color: "var(--card-accent)",
                  }}
                >
                  <card.icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span
                      aria-hidden
                      className="font-mono text-[0.6875rem] text-muted-foreground"
                    >
                      {card.ordinal}
                    </span>
                    <span className="truncate text-sm font-semibold">
                      {tNav(`items.${card.id}`)}
                    </span>
                  </span>

                  {card.isPending ? (
                    <Skeleton className="mt-2 h-4 w-24" />
                  ) : card.error ? null : (
                    <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      {/*  Both numbers, always — including zero, which is a real answer once
                          the request succeeded. A card that hid its zero would make an empty
                          Builder look like a Builder nobody had checked. */}
                      <Badge tone="success">
                        {t("publishedCount", { count: published })}
                      </Badge>
                      <Badge tone="neutral">
                        {t("draftCount", { count: drafts })}
                      </Badge>
                    </span>
                  )}
                </span>
                <ArrowRight
                  aria-hidden
                  className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform duration-150 group-hover:translate-x-0.5 motion-reduce:transition-none"
                />
              </Link>

              {/*  A failure is drawn as a failure, inside the card that failed — so one broken
                  endpoint costs one card rather than the whole row. */}
              {card.error ? (
                <div className="border-t border-border">
                  <ErrorState error={card.error} onRetry={card.refetch} />
                </div>
              ) : latest.length > 0 ? (
                <ul className="border-t border-border">
                  {latest.map((row) => (
                    <li key={row.id}>
                      <Link
                        href={`${card.href}/${row.id}`}
                        className={cn(
                          "flex items-center gap-2 px-4 py-2 transition-colors duration-150",
                          "hover:bg-accent motion-reduce:transition-none",
                          "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                        )}
                      >
                        <span
                          aria-hidden
                          className={cn(
                            "size-1.5 shrink-0 rounded-full",
                            row.status === "published"
                              ? "bg-success"
                              : "bg-muted-foreground/40",
                          )}
                        />
                        <span className="min-w-0 flex-1 truncate text-xs">
                          {row.name}
                        </span>
                        {/*  §4: timestamped. The date it last changed, in the reader's zone. */}
                        <span className="shrink-0 text-[0.6875rem] tabular-nums text-muted-foreground">
                          {formatDate(row.updated_at, format)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : card.isPending || card.error ? null : (
                <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
                  {t(`emptyAgent.${card.id}`)}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
