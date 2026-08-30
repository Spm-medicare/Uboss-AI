"use client";

import { ArrowRight, MapPin, Clock3, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { canSee, NAVIGATION } from "@/lib/shell/navigation";
import { cn } from "@/lib/cn";
import { Badge, LoadingState } from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * The first screen inside a workspace.
 *
 * PLAN §4 defines the Dashboard as pending tasks, approvals waiting, running and failed Agents,
 * upcoming schedules and recent outputs — *"Every metric is clickable, defined and timestamped."*
 * None of those exist yet: there are no tasks, no approvals and no runs in the product, so there
 * is nothing to count.
 *
 * The alternative is a wall of cards showing zeros or, worse, sample figures. `CLAUDE.md` is
 * blunt about which of those matters: *"Never display a value the backend did not return."* A
 * fabricated "3 approvals waiting" is not a placeholder, it is a number somebody will act on.
 *
 * **So the screen is built out of two things that are true right now**: what this session
 * actually returned — roles, permissions, placement, time zone — and where the person can
 * usefully go next, which is the set of screens that exist and that their permissions admit
 * them to. Both are read from the session, both are links to real routes, and neither is a
 * count of anything. The metrics arrive with the features that produce them, and this layout
 * has a place waiting for them above the fold.
 */
export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const tNav = useTranslations("nav");
  const tCommon = useTranslations("common");
  const { user } = useSession();

  if (!user) {
    //  Unreachable in practice — the shell resolves loading, error and signed-out above this
    //  point. Kept so the component is total rather than relying on that ordering.
    return (
      <AppShell title={t("title")}>
        <LoadingState />
      </AppShell>
    );
  }

  //  Only screens that exist (`buildsIn === null`) and that this person's actions admit them to.
  //  A card leading to a disabled screen would be an invitation to a dead end, which is a worse
  //  version of the thing the sidebar carefully avoids.
  const destinations = NAVIGATION.flatMap((group) => group.items)
    .filter((item) => item.buildsIn === null && item.href !== "/dashboard")
    .filter((item) => canSee(item, user.actions));

  return (
    <AppShell title={t("title")}>
      <div className="mx-auto max-w-5xl">
        {/*  ── who you are here ──────────────────────────────────────────── */}
        <header>
          <h2 className="text-[1.75rem] font-bold leading-tight tracking-tight">
            {t("welcome", {
              name: user.display_name.split(" ")[0] ?? user.display_name,
            })}
          </h2>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            {t("nothingYet")}
          </p>
        </header>

        {/*  Three facts the session returned, laid out so they can be read at a glance rather
            than parsed out of a table. Nothing here is computed, aggregated or estimated. */}
        <dl className="mt-7 grid gap-3 sm:grid-cols-3">
          <Fact
            icon={<ShieldCheck className="size-4" />}
            label={t("roles")}
            value={user.roles.map(readable).join(", ") || tCommon("none")}
          />
          <Fact
            icon={<MapPin className="size-4" />}
            label={t("hierarchyPosition")}
            value={user.org_node_id ? t("placed") : t("notPlaced")}
            muted={!user.org_node_id}
          />
          <Fact
            icon={<Clock3 className="size-4" />}
            label={t("timeZone")}
            value={user.timezone}
          />
        </dl>

        {/*  ── what you may do ───────────────────────────────────────────── */}
        <section className="mt-9" aria-labelledby="access-heading">
          <h3 id="access-heading" className="text-sm font-semibold">
            {t("accessHeading")}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{t("accessSubtitle")}</p>

          {user.actions.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {user.actions.map((action) => (
                <li key={action}>
                  {/*  The verb as the server returned it, spelled for a person. A permission is
                      the one thing on this screen somebody might screenshot and query, so it
                      says exactly what the token says and nothing rounder. */}
                  <Badge tone="neutral">{readable(action)}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">{t("nothingYouCan")}</p>
          )}
        </section>

        {/*  ── where to go ───────────────────────────────────────────────── */}
        {destinations.length > 0 ? (
          <section className="mt-9" aria-labelledby="start-heading">
            <h3 id="start-heading" className="text-sm font-semibold">
              {t("startHeading")}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">{t("startSubtitle")}</p>

            <ul className="mt-3 grid gap-3 sm:grid-cols-2">
              {destinations.map((item) => (
                <li key={item.id}>
                  <Link
                    href={item.href}
                    className={cn(
                      "group flex h-full items-start gap-3.5 rounded-xl border border-border bg-card p-4",
                      "transition-colors duration-150 hover:border-primary/40 hover:bg-accent motion-reduce:transition-none",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                    )}
                  >
                    <span
                      aria-hidden
                      className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"
                    >
                      <item.icon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-2">
                        {item.ordinal ? (
                          <span
                            aria-hidden
                            className="font-mono text-[0.6875rem] text-muted-foreground"
                          >
                            {item.ordinal}
                          </span>
                        ) : null}
                        <span className="text-sm font-semibold">
                          {tNav(`items.${item.id}`)}
                        </span>
                      </span>
                      <span className="mt-1 block text-sm leading-relaxed text-muted-foreground">
                        {t(`destination.${item.id}`)}
                      </span>
                    </span>
                    <ArrowRight
                      aria-hidden
                      className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform duration-150 group-hover:translate-x-0.5 motion-reduce:transition-none"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </AppShell>
  );
}

/** One fact from the session. A `dl` pair, so it is a definition and reads as one. */
function Fact({
  icon,
  label,
  value,
  muted = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <dt className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        <span aria-hidden className="text-muted-foreground">
          {icon}
        </span>
        {label}
      </dt>
      <dd
        className={cn(
          "mt-2 text-sm font-medium",
          muted ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * `edit_draft` reads badly on screen; "edit draft" does not.
 *
 * Formatting of a value the server returned, never a substitute for one — the underscores go and
 * the first letter is raised, and nothing else changes. A lookup table mapping keys to friendlier
 * names would be this screen inventing vocabulary the token does not carry, which is the thing a
 * permission display must never do.
 */
function readable(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
