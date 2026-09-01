"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { JobCard as Card_ } from "@/lib/api/contract";
import { can } from "@/lib/api/auth";
import { createJob, fetchJobs } from "@/lib/api/jobs";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { Alert, Badge, Button, Card, CardBody, Field, Input, QueryStates } from "@/ui";
import { toneFor, toneVars } from "@/ui/agent-tone";
import { AppShell } from "@/ui/shell/app-shell";
import { PageHeader } from "@/ui/shell/page-header";

/**
 * The Job cards.
 *
 * Deliberately the same screen as the Objective's list — same shape, same empty state, same
 * filters. PLAN §6 calls it the *shared* Builder experience, and a person who has learned one
 * list should not have to learn a second.
 *
 * `step_count` is a count of rows somebody typed. There is no completion percentage, because a
 * percentage needs a definition of "complete" that nobody has agreed and would be read as one.
 */
export default function JobBuilderPage() {
  const t = useTranslations("job");
  const { user } = useSession();
  const router = useRouter();
  const [filter, setFilter] = useState("");

  const jobs = useQuery({
    queryKey: ["jobs", filter],
    queryFn: ({ signal }) => fetchJobs(filter ? { status: filter, signal } : { signal }),
  });

  const mayCreate = can(user, "edit_draft");

  return (
    <AppShell
      title={t("jobs")}
      action={
        mayCreate ? (
          <NewJob onCreated={(id) => router.push(`/job-builder/${id}`)} />
        ) : undefined
      }
    >
      {/*  Wider than a reading column: the intro paragraph sets its own `max-w-prose`,
          and a grid of cards should use the width the window actually has. */}
      <div className="space-y-6">
        <PageHeader title={t("heading")} description={t("intro")} />

        <QueryStates
          isPending={jobs.isPending}
          error={jobs.error}
          onRetry={() => void jobs.refetch()}
        >
          {jobs.data?.is_empty ? (
            <Card>
              <CardBody className="space-y-4 py-12 text-center">
                <Workflow aria-hidden className="mx-auto size-8 text-muted-foreground" />
                <div className="space-y-1">
                  <p className="text-sm font-medium">{t("emptyTitle")}</p>
                  <p className="mx-auto max-w-sm text-sm leading-relaxed text-muted-foreground">
                    {mayCreate ? t("emptyBody") : t("emptyBodyReadOnly")}
                  </p>
                </div>
                {/*  The same control the top bar carries. An empty screen whose one
                    action lives only in the chrome asks somebody to go looking for it,
                    at the moment they have nothing else on the page to look at. */}
                {mayCreate ? (
                  <div className="flex justify-center">
                    <NewJob onCreated={(id) => router.push(`/job-builder/${id}`)} />
                  </div>
                ) : null}
              </CardBody>
            </Card>
          ) : (
            <>
              <Filters
                current={filter}
                onChange={setFilter}
                cards={jobs.data?.jobs ?? []}
              />

              {jobs.data && jobs.data.jobs.length === 0 ? (
                <Alert tone="info">
                  {t("noneMatching")}{" "}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => setFilter("")}
                  >
                    {t("clearFilter")}
                  </button>
                </Alert>
              ) : (
                <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,21rem),1fr))]">
                  {/*  Auto-fill on a minimum column width, not a fixed two: `sm:grid-cols-2`
                      gave every list exactly two columns whatever the window, so one card sat in
                      the left half with the right half empty and eight cards on a wide monitor
                      left a third of the screen unused. A floor keeps a card readable. */}
                  {(jobs.data?.jobs ?? []).map((card) => (
                    <JobTile key={card.id} card={card} />
                  ))}
                </ul>
              )}
            </>
          )}
        </QueryStates>
      </div>
    </AppShell>
  );
}

function Filters({
  current,
  onChange,
  cards,
}: {
  current: string;
  onChange: (value: string) => void;
  cards: Card_[];
}) {
  const t = useTranslations("job");
  //  **A fixed vocabulary, not a summary of what is on screen.** These were derived from the
  //  rows the server had already filtered, so picking "Draft" left one status in the list, tripped
  //  a `length < 2` guard, and removed the filter row entirely — with no way back to All short of
  //  reloading. The options a filter offers cannot depend on the filter's own result.
  const options = ["", "draft", "published"];
  //  Hidden only when there is nothing to filter *and* no filter is applied. With a filter on,
  //  the row stays even for an empty result, because that is the moment somebody needs it.
  if (cards.length === 0 && current === "") return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => (
        <button
          key={option || "all"}
          type="button"
          aria-pressed={current === option}
          onClick={() => onChange(option)}
          className={cn(
            "rounded-full border px-3 py-1 text-sm transition-colors duration-150",
            "motion-reduce:transition-none",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
            current === option
              ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
              : "border-border bg-card hover:bg-accent",
          )}
        >
          {option ? t(`status.${option}`) : t("allStatuses")}
        </button>
      ))}
    </div>
  );
}

function JobTile({ card }: { card: Card_ }) {
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

  return (
    <li>
      <Link
        href={`/job-builder/${card.id}`}
        //  The Agent's own hue, as a rail down the left edge. `border-l-[3px]` rather than a
        //  background wash: a tinted card competes with the status badge on it, and the badge is
        //  the one that carries meaning. The rail is identity, the badge is state.
        style={toneVars(toneFor("jobBuilder"))}
        className={cn(
          "group flex h-full flex-col gap-3 rounded-lg border border-border bg-card p-4",
          "border-l-[3px] border-l-[var(--card-accent)]",
          "transition-colors duration-150 hover:bg-[var(--card-soft)] motion-reduce:transition-none",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 flex-1 break-words font-medium leading-snug">{card.name}</p>
          <Badge tone={tones[card.status] ?? "neutral"}>{t(`status.${card.status}`)}</Badge>
        </div>

        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {card.objective_name ? (
            <div>
              <dt className="sr-only">{t("objective")}</dt>
              <dd>{card.objective_name}</dd>
            </div>
          ) : null}
          {card.department ? <dd>{card.department}</dd> : null}
          {card.frequency ? <dd>{card.frequency}</dd> : null}
        </dl>

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-3 text-xs">
          <span className="text-muted-foreground">
            {t("stepsRecorded", { count: card.step_count ?? 0 })}
          </span>
          <span className="flex items-center gap-1 text-primary opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none">
            {t("open")}
            <ArrowRight aria-hidden className="size-3.5" />
          </span>
        </div>
      </Link>
    </li>
  );
}

function NewJob({ onCreated }: { onCreated: (id: string) => void }) {
  const t = useTranslations("job");
  const tCommon = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () => createJob({ name: name.trim() }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      onCreated(result.id);
    },
  });

  if (!open) {
    return (
      <Button
        variant="primary"
        size="sm"
        icon={<Plus className="size-3.5" />}
        onClick={() => setOpen(true)}
      >
        {t("newJob")}
      </Button>
    );
  }

  return (
    <form
      className="flex items-end gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <Field label={t("jobName")} htmlFor="new-job" required>
        {(field) => (
          <Input
            {...field}
            value={name}
            autoFocus
            placeholder={t("newJobPlaceholder")}
            onChange={(event) => setName(event.target.value)}
            className="h-8 w-64 text-sm"
          />
        )}
      </Field>
      <Button
        type="submit"
        variant="primary"
        size="sm"
        busy={create.isPending}
        disabled={!name.trim()}
      >
        {t("start")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
        {tCommon("cancel")}
      </Button>
    </form>
  );
}
