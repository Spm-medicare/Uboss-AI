"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationTab,
} from "@/lib/api/notifications";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTime } from "@/lib/format";
import { Badge, Button, QueryStates } from "@/ui";

/** §12's three tabs, verbatim: *"All, Unread and Action required"*. */
const TABS: readonly NotificationTab[] = ["all", "unread", "action_required"];

/**
 * The bell's contents — §12's drawer.
 *
 * The drawer and the bell have existed since AS.5 showing a governed empty state, because
 * nothing real could fill them. This is what fills them, and it keeps the same rule that made
 * the empty state honest: **every value here came from the API**. There is no invented count, no
 * sample row, and an empty tab is only ever drawn after a successful response.
 *
 * `occurrences` is the one number worth explaining. A repeat of the same unresolved fact folds
 * into one row on the server, so a job that failed five times overnight is one line that says
 * five — not five lines. Showing the count is what makes the folding legible rather than making
 * it look like four notifications went missing.
 */
export function NotificationsPanel({
  timeZone,
  onNavigate,
}: {
  timeZone: string | undefined;
  /** Closes the drawer when a line is followed — the person has arrived where it pointed. */
  onNavigate: () => void;
}) {
  const t = useTranslations("notifications");
  const queryClient = useQueryClient();
  const format = contextFor(timeZone);
  const [tab, setTab] = useState<NotificationTab>("all");

  const list = useQuery({
    queryKey: ["notifications", "list", tab],
    queryFn: ({ signal }) => fetchNotifications(tab, signal),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
  }

  const read = useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onSuccess: refresh,
  });
  const readAll = useMutation({
    mutationFn: () => markAllNotificationsRead(),
    onSuccess: refresh,
  });

  const rows = list.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div role="tablist" aria-label={t("tabsLabel")} className="flex gap-1">
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              onClick={() => setTab(name)}
              className={cn(
                "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                tab === name
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent",
              )}
            >
              {t(`tabs.${name}`)}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          size="sm"
          busy={readAll.isPending}
          icon={<CheckCheck className="size-3.5" />}
          onClick={() => readAll.mutate()}
        >
          {t("readAll")}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <QueryStates
          isPending={list.isPending}
          error={list.error}
          isEmpty={rows.length === 0}
          emptyTitle={t(`empty.${tab}`)}
          emptyDescription={t("emptyWhy")}
          onRetry={() => void list.refetch()}
        >
          <ul className="divide-y divide-border">
            {rows.map((row) => (
              <li key={row.id}>
                <Link
                  href={row.deep_link}
                  onClick={() => {
                    //  Following a line is reading it. Marking read on click rather than on
                    //  render, because a drawer that cleared itself on being opened would lose
                    //  the list somebody opened it to look at.
                    if (!row.read_at) read.mutate(row.id);
                    onNavigate();
                  }}
                  className={cn(
                    "block px-3.5 py-3 transition-colors hover:bg-accent",
                    "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                    !row.read_at && "bg-primary/[0.04]",
                  )}
                >
                  <div className="flex items-start gap-2">
                    {/*  Unread is a dot as well as a tint. Colour alone is the one signal a
                        person with low vision does not get. */}
                    <span
                      aria-hidden
                      className={cn(
                        "mt-1.5 size-1.5 shrink-0 rounded-full",
                        row.read_at ? "bg-transparent" : "bg-primary",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-snug">
                        {row.title}
                        {row.occurrences > 1 ? (
                          <span className="ml-1.5 text-xs font-normal text-muted-foreground tabular-nums">
                            {t("times", { count: row.occurrences })}
                          </span>
                        ) : null}
                      </p>
                      {row.body ? (
                        <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                          {row.body}
                        </p>
                      ) : null}
                      <p className="mt-1 text-xs text-muted-foreground">
                        {row.actor_name ? `${row.actor_name} · ` : ""}
                        {formatDateTime(row.last_at, format)}
                      </p>
                    </div>
                    {row.action_required && !row.read_at ? (
                      <Badge tone="approval">{t("needsYou")}</Badge>
                    ) : null}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </QueryStates>
      </div>
    </div>
  );
}
