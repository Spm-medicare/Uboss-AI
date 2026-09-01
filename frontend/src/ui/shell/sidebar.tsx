"use client";

import { PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import type { CurrentUser } from "@/lib/api/auth";
import { cn } from "@/lib/cn";
import {
  canSee,
  navigationFor,
  SETTINGS_ITEM,
  type NavItem,
} from "@/lib/shell/navigation";
import { Monogram, Wordmark } from "@/ui/brand/mark";

/**
 * The dark sidebar of PLAN §29.
 *
 * *"The sidebar remains dark in both modes unless user testing proves otherwise."* — so it is
 * painted from the `--ub-sidebar-*` tokens rather than the page's, and it does not follow the
 * light/dark switch. That is why those tokens exist as a separate family.
 *
 * Collapsed, it is icons only. Two things must survive that:
 *
 * * **the accessible name**, which comes from the label text — kept in the DOM and hidden
 *   visually, never removed, so a screen reader still reads "Dashboard" and not an icon;
 * * **a visible tooltip**, since a sighted person who cannot read the icon has no other way to
 *   find out. §3 requires both: *"Icons have labels/tooltips and accessible focus states."*
 */
export function Sidebar({
  user,
  collapsed,
  onToggle,
  ready,
  counts,
  onOpenSettings,
}: {
  user: CurrentUser;
  collapsed: boolean;
  onToggle: () => void;
  ready: boolean;
  /**
   * Opens §13's Settings panel over the current screen.
   *
   * The row is not a `Link` for that reason: Settings is a panel you open and close, not a place
   * you navigate to and come back from. `/settings` remains a real route for a link somebody sends
   * — see `settings-dialog.tsx`.
   */
  onOpenSettings?: () => void;
  /** The avatar, workspace switcher and sign-out — §3's footer, built in AS.6. */
  /**
   * A number beside a row, keyed by item id. Passed in rather than fetched here, because the
   * sidebar renders on every screen and a component that made its own request would make one
   * on each of them. `undefined` draws nothing — a badge showing `0` while a count is still
   * loading is a number the backend has not returned.
   */
  counts?: Partial<Record<string, number>>;
}) {
  const t = useTranslations("nav");
  const tProduct = useTranslations("product");
  const pathname = usePathname();
  const navigation = navigationFor(user);

  return (
    <nav
      aria-label={t("primary")}
      data-collapsed={collapsed}
      className={cn(
        "flex h-dvh flex-col bg-sidebar text-sidebar-foreground",
        "border-r border-sidebar-border",
        collapsed ? "w-[var(--ub-sidebar-collapsed)]" : "w-[var(--ub-sidebar-expanded)]",
        //  Suppressed until the stored preference has been applied, so a remembered collapsed
        //  sidebar does not animate shut on every page load.
        ready && "transition-[width] duration-200 ease-[var(--ease-standard)]",
        "motion-reduce:transition-none",
      )}
    >
      <div
        className={cn(
          "flex h-[var(--ub-topbar-height)] shrink-0 items-center gap-2 px-3",
          collapsed && "justify-center",
        )}
      >
        {/*  The mark, and it survives the collapse. §3 makes the sidebar collapsible; a
            collapsed rail with no logo is a column of unattributed icons, and the one thing a
            person should never have to work out is which product they are in. The monogram
            alone is exactly what the collapsed width has room for. */}
        <Link
          href="/dashboard"
          aria-label={tProduct("name")}
          className={cn(
            "flex min-w-0 items-center gap-2.5 rounded-md",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
            collapsed && "hidden",
          )}
        >
          {/*  The same tile the signed-out panel uses. Somebody who has just signed in sees the
              mark move from one panel to the other rather than change shape. */}
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-white/10 ring-1 ring-inset ring-white/10">
            <Monogram className="h-[1.05rem] text-sidebar-foreground" />
          </span>
          {!collapsed ? (
            <Wordmark className="min-w-0 shrink truncate text-[0.9375rem] text-sidebar-foreground" />
          ) : null}
        </Link>
        {!collapsed ? (
          <span className="ml-auto">
            <SidebarButton
              onClick={onToggle}
              label={t("collapse")}
              icon={<PanelLeftClose className="size-4" />}
              expanded
            />
          </span>
        ) : (
          <SidebarButton
            onClick={onToggle}
            label={t("expand")}
            icon={<PanelLeftOpen className="size-4" />}
            expanded
          />
        )}
      </div>

      {/*  Nothing between the mark and the navigation.
          Two things used to sit here and both were in the way. A workspace card printed the
          workspace name directly above a nav group *also* labelled "Workspace" — the same word
          twice in three centimetres — and the name is now a line in the account menu, which is
          where somebody looks when they wonder which workspace they are in. And the collapse
          control was the second thing in the reading order, which is chrome for the chrome; it is
          at the foot now, with the other controls that are about the window rather than the
          work. */}

      {/*  **`overflow-x-hidden` is not belt-and-braces.** Setting `overflow-y` to anything but
          `visible` makes the *other* axis compute to `auto` as well, so this container grew a
          horizontal scrollbar — the stray `◀ ▶` at the foot of the rail — as soon as anything
          inside it was wider than the rail. What was wider was the collapsed tooltip, which is
          absolutely positioned at `left-full` and therefore counts toward scroll width.

          The tooltip is now a native `title` (see `SidebarItem`), which no overflow can clip, and
          this axis is pinned shut. */}
      <div
        className={cn(
          "ub-scroll-quiet min-h-0 flex-1 overflow-y-auto overflow-x-hidden pb-2",
          collapsed ? "px-2 pt-1" : "px-2",
        )}
      >
        {navigation.map((group) => {
          const visible = group.items.filter((item) => canSee(item, user.actions));
          //  A group whose every item is hidden leaves no heading behind. An empty "GOVERNED
          //  WORK" label is a promise of something that is not there.
          if (visible.length === 0) return null;

          //  **Every group renders the same way.** Agents used to be a disclosure — the one
          //  collapsible group — which hid four of the eight destinations behind a click on the
          //  screen whose only job is to show where you can go. It now reads like Workspace,
          //  because there was never a reason for it to read differently.
          return (
            <section
              key={group.id}
              //  On the rail the heading is `sr-only`, so the only thing saying "these four
              //  belong together" is the gap above them. It has to be clearly bigger than the
              //  gap between the items themselves or the column reads as one undifferentiated
              //  strip of icons.
              className={cn(collapsed ? "mt-6 first:mt-2" : "mt-5 first:mt-0")}
            >
              <h2
                className={cn(
                  "px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-sidebar-muted",
                  collapsed && "sr-only",
                )}
              >
                {t(`groups.${group.id}`)}
              </h2>
              <ul className={cn(collapsed ? "space-y-2.5" : "space-y-1")}>
                {visible.map((item) => (
                  <SidebarItem
                    key={item.id}
                    item={item}
                    collapsed={collapsed}
                    pathname={pathname}
                    count={counts?.[item.id]}
                  />
                ))}
              </ul>
            </section>
          );
        })}
      </div>

      {/*  The foot: Settings, the way out, and the width of the rail itself. Appearance moved to
          the top bar as a light/dark switch — it is a property of the window you are looking at,
          so it belongs on the chrome rather than in the menu. */}
      <div
        className={cn(
          "shrink-0 border-t border-sidebar-border p-2",
          //  Three controls of three sizes used to stack here with no shared rhythm, and the
          //  avatar was clipped by the padding. One centred column, spaced like the nav above.
          collapsed && "flex flex-col items-center gap-2.5 py-3",
        )}
      >
        {/*  **A row, not an icon.** As a bare glyph under the wordmark this was unlabelled chrome
            in the most valuable position on the screen. Here it is a control that says what it
            does — and collapsed, it is the one row whose icon points the way it will move, which
            is the only affordance a 3.5rem rail has room for. */}
        <ul className={cn(collapsed ? "space-y-2.5" : "space-y-1")}>
          <SidebarItem
            item={SETTINGS_ITEM}
            icon={Settings}
            collapsed={collapsed}
            pathname={pathname}
            {...(onOpenSettings ? { onActivate: onOpenSettings } : {})}
          />
        </ul>
      </div>
    </nav>
  );
}

/**
 * One row.
 *
 * An item whose screen is not built yet renders as a disabled row that says which gate builds it.
 * The alternative — a link to a route that 404s — is a control that does not do what it says, and
 * hiding it would read as "you do not have access", which is a different and untrue statement.
 */
function SidebarItem({
  item,
  collapsed,
  pathname,
  icon: Override,
  count,
  onActivate,
}: {
  item: NavItem;
  collapsed: boolean;
  pathname: string;
  icon?: NavItem["icon"];
  /** How many things are waiting on this person here. Never invented, never a zero. */
  count?: number | undefined;
  /**
   * When present, the row is a button that does this instead of a link that navigates. One row
   * uses it — Settings, which opens a panel — and it is a prop rather than a special case inside
   * this component so the next one does not need an `if (item.id === …)`.
   */
  onActivate?: () => void;
}) {
  const t = useTranslations("nav");
  const Icon = Override ?? item.icon;
  const label = t(`items.${item.id}`);
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);

  const inner = (
    <>
      <Icon aria-hidden className="size-4 shrink-0" />
      {collapsed ? (
        <span className="sr-only">{label}</span>
      ) : (
        <>
          {item.ordinal ? (
            <span
              aria-hidden
              className="shrink-0 font-mono text-[0.6875rem] text-sidebar-muted"
            >
              {item.ordinal}
            </span>
          ) : null}
          <span className="min-w-0 flex-1 truncate">{label}</span>
        </>
      )}
      {/*  The count reads as part of the row's name — "To-do list, 3 waiting" — rather than as
          a bare number a screen reader would announce with no idea what it counts. */}
      {count !== undefined && count > 0 ? (
        <span
          className={cn(
            "shrink-0 rounded-full bg-primary px-1.5 py-0.5 text-[0.6875rem]",
            "font-semibold tabular-nums text-primary-foreground",
            collapsed && "absolute right-1 top-1 px-1 py-0",
          )}
        >
          <span aria-hidden>{count}</span>
          <span className="sr-only">{t("waiting", { count })}</span>
        </span>
      ) : null}
    </>
  );

  const shape = cn(
    "group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
    "transition-colors duration-150 motion-reduce:transition-none",
    "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
    collapsed && "justify-center px-0",
  );

  if (item.buildsIn) {
    return (
      <li>
        <span
          //  A real disabled control, not a dimmed link: it cannot be focused into a dead end,
          //  and assistive technology is told why rather than left to infer it from the colour.
          aria-disabled
          title={
            collapsed
              ? `${label} — ${t("notBuiltYet", { gate: item.buildsIn })}`
              : t("notBuiltYet", { gate: item.buildsIn })
          }
          className={cn(shape, "cursor-not-allowed text-sidebar-muted opacity-60")}
        >
          {inner}
          {!collapsed ? (
            <span className="shrink-0 text-[0.6875rem] uppercase tracking-wide">
              {t("soon")}
            </span>
          ) : null}
        </span>
      </li>
    );
  }

  if (onActivate) {
    return (
      <li>
        <button
          type="button"
          onClick={onActivate}
          //  `aria-haspopup="dialog"` so the row announces what it does: it opens a panel rather
          //  than taking you somewhere, and a screen reader should say so before the click.
          aria-haspopup="dialog"
          title={collapsed ? label : undefined}
          className={cn(shape, "w-full text-sidebar-foreground hover:bg-sidebar-hover")}
        >
          {inner}
        </button>
      </li>
    );
  }

  return (
    <li>
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        className={cn(
          shape,
          active
            ? "bg-sidebar-active font-semibold text-sidebar-foreground"
            : "text-sidebar-muted hover:bg-sidebar-surface hover:text-sidebar-foreground",
        )}
      >
        {/*  A bar as well as a fill. Colour alone is the one signal a person with low vision or
            a monochrome display does not get, and "which screen am I on" is not a detail. */}
        {active ? (
          <span
            aria-hidden
            className="absolute inset-y-1.5 left-0 w-[3px] rounded-r-full bg-primary"
          />
        ) : null}
        {inner}
      </Link>
    </li>
  );
}

function SidebarButton({
  onClick,
  label,
  icon,
  expanded,
}: {
  onClick: () => void;
  label: string;
  icon: ReactNode;
  expanded?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={expanded}
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-md text-sidebar-muted",
        "transition-colors duration-150 hover:bg-sidebar-surface hover:text-sidebar-foreground",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        "motion-reduce:transition-none",
      )}
    >
      {icon}
    </button>
  );
}
