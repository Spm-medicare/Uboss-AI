"use client";

import { ChevronDown, PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import type { CurrentUser } from "@/lib/api/auth";
import { cn } from "@/lib/cn";
import {
  canSee,
  NAVIGATION,
  SETTINGS_ITEM,
  type NavItem,
} from "@/lib/shell/navigation";
import { useAgentsGroup } from "@/lib/shell/use-sidebar";

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
  footer,
}: {
  user: CurrentUser;
  collapsed: boolean;
  onToggle: () => void;
  ready: boolean;
  /** The avatar, workspace switcher and sign-out — §3's footer, built in AS.6. */
  footer: ReactNode;
}) {
  const t = useTranslations("nav");
  const tProduct = useTranslations("product");
  const pathname = usePathname();
  const agents = useAgentsGroup();

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
        <span
          aria-hidden
          className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground"
        >
          U
        </span>
        {!collapsed ? (
          <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">
            {tProduct("name")}
          </span>
        ) : null}
        {!collapsed ? (
          <SidebarButton
            onClick={onToggle}
            label={t("collapse")}
            icon={<PanelLeftClose className="size-4" />}
            expanded
          />
        ) : null}
      </div>

      {collapsed ? (
        <div className="flex justify-center pb-2">
          <SidebarButton
            onClick={onToggle}
            label={t("expand")}
            icon={<PanelLeftOpen className="size-4" />}
          />
        </div>
      ) : (
        <p className="truncate px-4 pb-3 text-xs text-sidebar-muted">
          {user.workspace_name}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {NAVIGATION.map((group) => {
          const visible = group.items.filter((item) => canSee(item, user.actions));
          //  A group whose every item is hidden leaves no heading behind. An empty "GOVERNED
          //  WORK" label is a promise of something that is not there.
          if (visible.length === 0) return null;

          if (group.collapsible) {
            return (
              <section key={group.id} className="mt-4">
                <button
                  type="button"
                  onClick={agents.toggle}
                  aria-expanded={agents.open}
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5",
                    "text-xs font-semibold uppercase tracking-wide text-sidebar-muted",
                    "transition-colors duration-150 hover:text-sidebar-foreground",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                    collapsed && "sr-only",
                  )}
                >
                  <ChevronDown
                    aria-hidden
                    className={cn(
                      "size-3.5 transition-transform duration-150 motion-reduce:transition-none",
                      !agents.open && "-rotate-90",
                    )}
                  />
                  {t(`groups.${group.id}`)}
                </button>
                {/*  Collapsed, the group is always shown: its own disclosure is meaningless when
                    the heading it belongs to is not visible. */}
                {agents.open || collapsed ? (
                  <ul className="mt-1 space-y-0.5">
                    {visible.map((item) => (
                      <SidebarItem
                        key={item.id}
                        item={item}
                        collapsed={collapsed}
                        pathname={pathname}
                      />
                    ))}
                  </ul>
                ) : null}
              </section>
            );
          }

          return (
            <section key={group.id} className="mt-4 first:mt-0">
              <h2
                className={cn(
                  "px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-sidebar-muted",
                  collapsed && "sr-only",
                )}
              >
                {t(`groups.${group.id}`)}
              </h2>
              <ul className="space-y-0.5">
                {visible.map((item) => (
                  <SidebarItem
                    key={item.id}
                    item={item}
                    collapsed={collapsed}
                    pathname={pathname}
                  />
                ))}
              </ul>
            </section>
          );
        })}
      </div>

      <div className="shrink-0 border-t border-sidebar-border p-2">
        <ul className="space-y-0.5">
          <SidebarItem
            item={SETTINGS_ITEM}
            icon={Settings}
            collapsed={collapsed}
            pathname={pathname}
          />
        </ul>
        {footer}
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
}: {
  item: NavItem;
  collapsed: boolean;
  pathname: string;
  icon?: NavItem["icon"];
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
    </>
  );

  const shape = cn(
    "group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
    "transition-colors duration-150 motion-reduce:transition-none",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
    collapsed && "justify-center px-0",
  );

  if (item.buildsIn) {
    return (
      <li>
        <span
          //  A real disabled control, not a dimmed link: it cannot be focused into a dead end,
          //  and assistive technology is told why rather than left to infer it from the colour.
          aria-disabled
          title={t("notBuiltYet", { gate: item.buildsIn })}
          className={cn(shape, "cursor-not-allowed text-sidebar-muted opacity-60")}
        >
          {inner}
          {!collapsed ? (
            <span className="shrink-0 text-[0.6875rem] uppercase tracking-wide">
              {t("soon")}
            </span>
          ) : null}
          {collapsed ? <Tooltip>{label}</Tooltip> : null}
        </span>
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
            ? "bg-sidebar-active font-medium text-sidebar-foreground"
            : "text-sidebar-muted hover:bg-sidebar-surface hover:text-sidebar-foreground",
        )}
      >
        {inner}
        {collapsed ? <Tooltip>{label}</Tooltip> : null}
      </Link>
    </li>
  );
}

/**
 * The label a collapsed icon needs.
 *
 * CSS-only, shown on hover and on keyboard focus. `aria-hidden` because the label is already in
 * the accessible name — a tooltip that repeats it makes a screen reader say everything twice.
 */
function Tooltip({ children }: { children: ReactNode }) {
  return (
    <span
      aria-hidden
      role="presentation"
      className={cn(
        "pointer-events-none absolute left-full top-1/2 z-20 ml-2 -translate-y-1/2",
        "whitespace-nowrap rounded-md bg-sidebar-surface px-2 py-1 text-xs",
        "text-sidebar-foreground opacity-0 shadow-popover",
        "transition-opacity duration-150 motion-reduce:transition-none",
        "group-hover:opacity-100 group-focus-visible:opacity-100",
      )}
    >
      {children}
    </span>
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
