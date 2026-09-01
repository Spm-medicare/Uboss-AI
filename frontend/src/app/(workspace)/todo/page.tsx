"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { can } from "@/lib/api/auth";
import type {
  PersonRef,
  TaskCounts,
  TaskKind,
  TaskRead,
  TaskTab,
} from "@/lib/api/contract";
import { fetchPeople } from "@/lib/api/objectives";
import { escalateApproval } from "@/lib/api/approvals";
import {
  commentOnTask,
  completeTask,
  declineTask,
  delegateTask,
  fetchTask,
  fetchTaskCounts,
  fetchTasks,
  followTask,
  startTask,
} from "@/lib/api/tasks";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTime } from "@/lib/format";
import { Alert, Badge, Card, QueryStates } from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";
import { PageHeader } from "@/ui/shell/page-header";
import { TaskPanel } from "@/ui/tasks/task-panel";
import { KIND_TONE, STATE_TONE } from "@/ui/tasks/tone";

/** §11's five tabs, verbatim and in the order the plan lists them. */
const TABS: readonly TaskTab[] = [
  "mine",
  "approvals",
  "input",
  "following",
  "completed",
];
const KINDS: readonly TaskKind[] = ["work", "input", "approval"];

/**
 * The To-do list — PLAN §11.
 *
 * **A task on this screen is always work a run is waiting for.** There is no "add a task": the
 * only way something appears here is that a published Job reached a human step, which is what
 * separates a governed work list from a notes app with a tick box.
 *
 * Three things this screen refuses to do, all of them from `CLAUDE.md`:
 *
 * * **No invented numbers.** Every count comes from `/tasks/counts`; nothing is derived from the
 *   page of rows on screen, which would disagree with the badge the moment a filter is applied.
 * * **A failure renders a failure.** An empty tab and a tab that could not be loaded look nothing
 *   alike, because they mean opposite things.
 * * **No control that does not act.** The panel offers only outcomes the task's kind allows and
 *   only to somebody the server would let through.
 */
export default function TodoPage() {
  const t = useTranslations("todo");
  const { user } = useSession();
  const queryClient = useQueryClient();
  const when = contextFor(user?.timezone ?? undefined);

  const [tab, setTab] = useState<TaskTab>("mine");
  const [kind, setKind] = useState<TaskKind | null>(null);
  //  Not a sixth tab — §11 names five. Unassigned work has to be reachable by somebody who may
  //  hand it out, or it exists in nobody's list at all; so it is a toggle, offered only to them.
  const [unassigned, setUnassigned] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const counts = useQuery({
    queryKey: ["tasks", "counts"],
    queryFn: ({ signal }) => fetchTaskCounts(signal),
  });
  const shown: TaskTab = unassigned ? "unassigned" : tab;
  const list = useQuery({
    queryKey: ["tasks", "list", shown, kind],
    queryFn: ({ signal }) =>
      fetchTasks({ tab: shown, ...(kind ? { kind } : {}), signal }),
  });
  const opened = useQuery({
    queryKey: ["tasks", "one", openId],
    queryFn: ({ signal }) => fetchTask(openId!, signal),
    enabled: openId !== null,
  });
  //  Only fetched when the panel is open: the delegate list is the one thing on this screen that
  //  is not about the person's own work, and loading it on arrival would be a request nobody
  //  asked for on every visit.
  const people = useQuery({
    queryKey: ["people"],
    queryFn: ({ signal }) => fetchPeople(signal),
    enabled: openId !== null,
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
  }

  /**
   * Every action on a task, through one mutation.
   *
   * One rather than seven because they share the same three consequences — the failure is shown
   * as a real error, the lists and the counts are re-read, and the panel follows whichever task
   * now exists. Seven copies of that is seven places for one of the three to be forgotten.
   */
  const act = useMutation({
    mutationFn: async (action: () => Promise<TaskRead | void>) => action(),
    onMutate: () => setFailure(null),
    onSuccess: (result) => {
      refresh();
      //  Delegating closes this task and opens a new one; following the returned id keeps the
      //  panel on the task that now exists rather than on the closed one.
      if (result && result.id !== openId) setOpenId(result.id);
    },
    onError: (error: Error) => setFailure(error.message),
  });

  const rows = list.data ?? [];
  const mayAssign = can(user, "assign");

  return (
    <AppShell title={t("title")}>
      <div className="space-y-5">
        <PageHeader title={t("heading")} description={t("intro")} />

        {failure ? (
          <Alert tone="danger" title={t("actionFailed")}>
            {failure}
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div role="tablist" aria-label={t("tabsLabel")} className="flex flex-wrap gap-1">
            {TABS.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={!unassigned && tab === name}
                onClick={() => {
                  setTab(name);
                  setUnassigned(false);
                }}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  !unassigned && tab === name
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                {t(`tabs.${name}`)}
                {/*  Only the three the API counts. A number beside "All" would have to be
                    invented, and an invented number on a work list is one people learn to
                    distrust — so those tabs carry no badge at all. */}
                {countFor(name, counts.data) !== null ? (
                  <span
                    className={cn(
                      "ml-1.5 rounded-full px-1.5 py-0.5 text-xs tabular-nums",
                      !unassigned && tab === name ? "bg-white/20" : "bg-muted",
                    )}
                  >
                    {countFor(name, counts.data)}
                  </span>
                ) : null}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1">
            <FilterChip
              label={t("kinds.all")}
              active={kind === null}
              onClick={() => setKind(null)}
            />
            {KINDS.map((name) => (
              <FilterChip
                key={name}
                label={t(`kinds.${name}`)}
                active={kind === name}
                onClick={() => setKind(name)}
              />
            ))}
            {mayAssign ? (
              <>
                <span aria-hidden className="mx-1 h-4 w-px bg-border" />
                <FilterChip
                  label={
                    counts.data
                      ? `${t("unassigned")} ${counts.data.unassigned}`
                      : t("unassigned")
                  }
                  title={t("unassignedHint")}
                  active={unassigned}
                  onClick={() => setUnassigned((was) => !was)}
                />
              </>
            ) : null}
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <Card>
            <QueryStates
              isPending={list.isPending}
              error={list.error}
              isEmpty={rows.length === 0}
              emptyTitle={t(`empty.${shown}`)}
              emptyDescription={t("emptyWhy")}
              onRetry={() => void list.refetch()}
            >
              <ul className="divide-y divide-border">
                {rows.map((task) => (
                  <li key={task.id}>
                    <button
                      type="button"
                      onClick={() => setOpenId(task.id)}
                      aria-current={openId === task.id}
                      className={cn(
                        "flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors",
                        "hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                        openId === task.id && "bg-accent",
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{task.title}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {task.assignee_name
                            ? t("assignedTo", { name: task.assignee_name })
                            : t("assignedToNobody")}
                          {" · "}
                          {formatDateTime(task.created_at, when)}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {task.following ? (
                          <Star aria-label={t("following")} className="size-3.5 fill-current text-muted-foreground" />
                        ) : null}
                        <Badge tone={KIND_TONE[task.kind] ?? "neutral"}>
                          {t(`kinds.${task.kind}`)}
                        </Badge>
                        <Badge tone={STATE_TONE[task.state] ?? "neutral"} outline>
                          {t(`states.${task.state}`)}
                        </Badge>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </QueryStates>
          </Card>

          <Card className="lg:sticky lg:top-4 lg:h-[calc(100dvh-8rem)] lg:overflow-hidden">
            {openId === null ? (
              <p className="px-5 py-12 text-center text-sm text-muted-foreground">
                {t("pickOne")}
              </p>
            ) : (
              <QueryStates
                isPending={opened.isPending}
                error={opened.error}
                onRetry={() => void opened.refetch()}
              >
                {opened.data ? (
                  <TaskPanel
                    task={opened.data}
                    people={peopleFor(people.data, opened.data.assignee_membership_id)}
                    busy={act.isPending}
                    canAct={
                      opened.data.assignee_membership_id === user?.membership_id ||
                      (opened.data.assignee_membership_id === null && mayAssign)
                    }
                    formatWhen={(iso) => formatDateTime(iso, when)}
                    onStart={() => act.mutate(() => startTask(opened.data.id))}
                    onComplete={(outcome, note) =>
                      act.mutate(() => completeTask(opened.data.id, outcome, note))
                    }
                    onDecline={(reason) =>
                      act.mutate(() => declineTask(opened.data.id, reason))
                    }
                    onDelegate={(to, note) =>
                      act.mutate(() => delegateTask(opened.data.id, to, note))
                    }
                    onComment={(body) =>
                      act.mutate(() => commentOnTask(opened.data.id, body))
                    }
                    onFollow={() =>
                      act.mutate(() =>
                        followTask(opened.data.id, opened.data.following),
                      )
                    }
                    onEscalate={(to, note) => {
                      //  Only ever reachable on an approval task, because that is the only kind
                      //  the panel offers it for — and the id it needs is the approval's, not
                      //  the task's.
                      const id = opened.data.approval?.id;
                      if (!id) return;
                      //  Returns the approval, not the task; mapped to `void` so the panel stays
                      //  on the task it is already showing rather than trying to follow an id
                      //  from a different table.
                      act.mutate(async () => {
                        await escalateApproval(id, to, note);
                      });
                    }}
                    onClose={() => setOpenId(null)}
                  />
                ) : null}
              </QueryStates>
            )}
          </Card>
        </div>
      </div>
    </AppShell>
  );
}

function FilterChip({
  label,
  active,
  onClick,
  title,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      {...(title ? { title } : {})}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active
          ? "border-transparent bg-foreground text-background"
          : "border-border text-muted-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}

/**
 * The badge beside a tab, or `null` where the API does not count it.
 *
 * *Completed* has no number on purpose: it is a history, and a count of everything a person has
 * ever done is not something anybody acts on. Nothing here is derived from the rows on screen —
 * that would change with the kind filter and disagree with the tab it labels.
 */
function countFor(tab: TaskTab, counts: TaskCounts | undefined): number | null {
  if (!counts) return null;
  if (tab === "mine") return counts.mine_open;
  if (tab === "approvals") return counts.approvals;
  if (tab === "input") return counts.input_requested;
  if (tab === "following") return counts.following_open;
  if (tab === "unassigned") return counts.unassigned;
  return null;
}

/** Everybody except whoever already holds it — delegating to them is refused by the server. */
function peopleFor(
  people: readonly PersonRef[] | undefined,
  holder: string | null | undefined,
): readonly PersonRef[] {
  return (people ?? []).filter((person) => person.membership_id !== holder);
}
