"use client";

import { ArrowRight, MapPin, Clock3, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { canSee, NAVIGATION } from "@/lib/shell/navigation";
import { cn } from "@/lib/cn";
import { LoadingState } from "@/ui";
import { AgentCards } from "@/ui/dashboard/agent-cards";
import { DashboardMetrics } from "@/ui/dashboard/metrics";
import { AppShell } from "@/ui/shell/app-shell";
import { toneFor, toneVars } from "@/ui/agent-tone";
import { PageHeader } from "@/ui/shell/page-header";

/**
 * The first screen inside a workspace — PLAN §4.
 *
 * §4's purpose is one sentence: *"show what needs attention now"*, and *"every metric is
 * clickable, defined and timestamped."*
 *
 * This screen used to say the opposite. Its comment read *"None of those exist yet: there are no
 * tasks, no approvals and no runs in the product, so there is nothing to count"* — true when it
 * was written, and false from Gate 7.1 onward. It was also **contradicted on screen**: the shell
 * around it was already badging the sidebar from `/tasks/counts` and the bell from
 * `/notifications/counts`, so somebody with seven open tasks read "7 waiting on you" in the rail
 * and "nothing has been built yet" in the body.
 *
 * The honesty rule that produced that comment is still the right rule; it just belongs to
 * *rendering* rather than to a claim about the backend:
 *
 * * a number is drawn only from a resolved response;
 * * a failed request draws an error, **never** a zero — "nothing is waiting on you" and "we could
 *   not find out" are opposite statements;
 * * a resolved zero is drawn as a real zero, because it is a real answer.
 *
 * The layout follows the question order: what needs doing, then the four Agents and what they
 * hold, then who you are here — which is the only part somebody reads once and never again.
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
      <div>
        {/*  ── who you are here ──────────────────────────────────────────── */}
        {/*  The shared component, like every other workspace screen. A hand-rolled heading here
            was a second set of type sizes to keep in step with the first. */}
        <PageHeader
          title={t("welcome", {
            name: user.display_name.split(" ")[0] ?? user.display_name,
          })}
          description={t("intro")}
        />

        {/*  ── what needs attention now ──────────────────────────────────── */}
        {/*  §4's purpose in one line: *"show what needs attention now"*. It goes first,
            above the session facts, because the answer to "what should I do" outranks the
            answer to "who am I here" on every visit after the first. */}
        <div className="mt-7">
          <DashboardMetrics timeZone={user.timezone} />
        </div>

        {/*  ── the four Agents ───────────────────────────────────────────── */}
        {/*  §3 numbers them 01 to 04 and §4 asks for *"quick actions that route into the correct
            Builder"*. Each card carries its own real counts and its three most recently changed
            records, so the row is a way in rather than a menu. */}
        <div className="mt-9">
          <AgentCards timeZone={user.timezone} actions={user.actions} />
        </div>

        {/*  Three facts the session returned, laid out so they can be read at a glance rather
            than parsed out of a table. Nothing here is computed, aggregated or estimated. */}
        <h3 className="mt-9 text-sm font-semibold">{t("youHeading")}</h3>
        <dl className="mt-3 grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))]">
          <Fact
            icon={<ShieldCheck className="size-4" />}
            label={t("roles")}
            value={user.roles.map(spelled).join(", ") || tCommon("none")}
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

        {/*  ── where to go ───────────────────────────────────────────────── */}
        {destinations.length > 0 ? (
          <section className="mt-9" aria-labelledby="start-heading">
            <h3 id="start-heading" className="text-sm font-semibold">
              {t("startHeading")}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">{t("startSubtitle")}</p>

            <ul className="mt-3 grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))]">
              {destinations.map((item) => (
                <li key={item.id}>
                  <Link
                    href={item.href}
                    style={toneVars(toneFor(item.id))}
                    className={cn(
                      "group flex h-full items-start gap-3.5 rounded-xl border border-border bg-card p-4",
                      "border-l-[3px] border-l-[var(--card-accent)]",
                      "transition-colors duration-150 hover:bg-[var(--card-soft)] motion-reduce:transition-none",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
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
 * `workspace_owner` reads badly on screen; "Workspace owner" does not.
 *
 * Formatting of a value the server returned, never a substitute for one — the underscores go and
 * the first letter is raised, and nothing else changes. A lookup table mapping keys to friendlier
 * names would be this screen inventing vocabulary the token does not carry, which is the thing a
 * role display must never do.
 */
function spelled(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
