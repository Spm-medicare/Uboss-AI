"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, Menu, Sparkles, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { fetchNotificationCounts } from "@/lib/api/notifications";
import type { CurrentUser } from "@/lib/api/auth";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";
import { CopilotPanel } from "@/ui/shell/copilot-panel";
import { GlobalSearch } from "@/ui/shell/global-search";
import { HeaderAccount, ThemeSwitch } from "@/ui/shell/header-account";
import { NotificationsPanel } from "@/ui/shell/notifications-panel";

/**
 * The compact top bar of PLAN §3:
 *
 *     Breadcrumb/title | Global search | Context action | Notifications | UBOSS Copilot
 *
 * All five are connected as of Gate 7. Three of them were not, for six gates, and what they did
 * in the meantime is the part worth keeping in mind: the search box was disabled and said why, the
 * bell carried no number at all, and the Copilot drawer held one honest sentence. The work
 * breakdown asked for exactly that — *"Search shows an honest unavailable state until Gate 7.
 * Notifications and Copilot show governed empty states. No fake activity, no invented counts."*
 *
 * The bell still shows nothing rather than `0` when the count fails. An empty bell is accurate; a
 * `0` would claim the number is known.
 */
export function Topbar({
  title,
  breadcrumb,
  action,
  onOpenNavigation,
  timeZone,
  user,
  onOpenSettings,
}: {
  title: string;
  /** Ancestors, nearest last. The current screen is the `title` and is never repeated here. */
  breadcrumb?: { label: string; href: string }[];
  /** The one context action for this screen — §29's "one clear primary action per screen". */
  action?: ReactNode;
  /** Opens the mobile drawer. Absent on wide screens, where the sidebar is always present. */
  onOpenNavigation: () => void;
  /** The reader's own zone, so every instant in the drawer is shown where they are. */
  timeZone?: string | undefined;
  /** The signed-in person. Their name and the way out live here, not in the sidebar. */
  user: CurrentUser;
  /** Opens §13's Settings panel over the current screen. */
  onOpenSettings: () => void;
}) {
  const t = useTranslations("shell");
  const [drawer, setDrawer] = useState<"notifications" | "copilot" | null>(null);

  //  The badge. Real since Gate 7.5 — before that the bell deliberately carried no number,
  //  because an invented one is worse than none. A failed count still shows nothing rather than
  //  a `0`, which would claim the number is known.
  const counts = useQuery({
    queryKey: ["notifications", "counts"],
    queryFn: ({ signal }) => fetchNotificationCounts(signal),
  });
  const unread = counts.data?.unread ?? 0;

  //  **A crumb that repeats the title is dropped.** Three screens read "Job Builder / Job
  //  Builder" because the list's name and the builder's name are the same words — which is
  //  correct in the message catalogue and wrong on the screen. Fixed here rather than by
  //  renaming three strings, so the next screen whose parent shares its name cannot bring the
  //  duplicate back.
  const trail = (breadcrumb ?? []).filter(
    (crumb) => crumb.label.trim().toLowerCase() !== title.trim().toLowerCase(),
  );

  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex h-[var(--ub-topbar-height)] shrink-0 items-center gap-3",
        "border-b border-border bg-background px-4 sm:px-6",
      )}
    >
      <Button
        variant="ghost"
        size="sm"
        className="lg:hidden"
        aria-label={t("openNavigation")}
        onClick={onOpenNavigation}
        icon={<Menu className="size-4" />}
      />

      <div className="min-w-0 flex-1">
        {trail.length > 0 ? (
          <nav aria-label={t("breadcrumb")}>
            <ol className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {trail.map((crumb, index) => (
                <li key={crumb.href} className="flex items-center gap-1.5">
                  <a
                    href={crumb.href}
                    className="truncate rounded-sm underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]"
                  >
                    {crumb.label}
                  </a>
                  {/*  A separator *between* crumbs. It was emitted after every one, so the trail
                      ended in a slash pointing at nothing. */}
                  {index < trail.length - 1 ? <span aria-hidden>/</span> : null}
                </li>
              ))}
            </ol>
          </nav>
        ) : null}
        <h1 className="truncate text-sm font-semibold">{title}</h1>
      </div>

      <GlobalSearch />

      {/*  **One group, and it does not shrink.** Before this the bar was a flat row: a screen
          whose `action` is an inline create form — a 16rem input plus two buttons — competed with
          the search box, the bell and the Copilot for the same line, and between `md` and `lg` the
          row overflowed the window. Grouping the right side and pinning it `shrink-0` makes the
          title the only thing that gives, which is right: it truncates, and it is the one item
          repeated in the browser tab. */}
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {action}

        <span className="relative inline-flex">
        <Button
          variant="ghost"
          size="sm"
          aria-label={
            unread > 0 ? t("notificationsWith", { count: unread }) : t("notifications")
          }
          aria-expanded={drawer === "notifications"}
          onClick={() =>
            setDrawer(drawer === "notifications" ? null : "notifications")
          }
          icon={<Bell className="size-4" />}
        />
        {unread > 0 ? (
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute -right-0.5 -top-0.5 min-w-[1.05rem]",
              "rounded-full bg-primary px-1 text-center text-[0.625rem] font-semibold",
              "leading-[1.05rem] text-primary-foreground tabular-nums",
            )}
          >
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </span>

        <Button
          variant="ghost"
          size="sm"
          aria-label={t("copilot")}
          aria-expanded={drawer === "copilot"}
          onClick={() => setDrawer(drawer === "copilot" ? null : "copilot")}
          icon={<Sparkles className="size-4" />}
        />

        <ThemeSwitch />

        <span aria-hidden className="mx-0.5 h-5 w-px bg-border" />

        <HeaderAccount user={user} onOpenSettings={onOpenSettings} />
      </div>

      {drawer ? (
        <Drawer
          title={drawer === "notifications" ? t("notifications") : t("copilot")}
          onClose={() => setDrawer(null)}
        >
          {drawer === "notifications" ? (
            <NotificationsPanel
              timeZone={timeZone}
              onNavigate={() => setDrawer(null)}
            />
          ) : (
            <CopilotPanel onNavigate={() => setDrawer(null)} />
          )}
        </Drawer>
      ) : null}
    </header>
  );
}

/**
 * The right-hand panel §29 calls the "optional right Copilot/help drawer".
 *
 * A dialog, so focus is trapped inside it and Escape closes it. Both are what makes it usable for
 * someone on a keyboard, and both are what a `<div>` with an onClick does not give.
 *
 * The trap was documented here before it existed — the panel took focus on open and handled
 * Escape, but Tab walked straight out of an `aria-modal="true"` region into the page behind it.
 * It is implemented now, in the same shape `ui/dialog.tsx` uses: only the two ends of the tab
 * order are handled, because everything between them is the browser's own order and is correct.
 */
function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const t = useTranslations("common");
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    //  Focus moves into the drawer, so the next Tab is inside it rather than back at the top of
    //  the page — otherwise a keyboard user opens a panel they then cannot reach.
    panel.current?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  /** Tab wrapping, so an `aria-modal` region actually behaves like one. */
  function trap(event: React.KeyboardEvent) {
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      panel.current?.querySelectorAll<HTMLElement>(
        'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    if (focusable.length === 0) return;

    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className="fixed inset-0 z-40 bg-black/20"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={trap}
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-[var(--ub-drawer-width)] max-w-full flex-col",
          "border-l border-border bg-background shadow-dialog",
          "focus-visible:outline-none",
        )}
      >
        <div className="flex h-[var(--ub-topbar-height)] shrink-0 items-center justify-between border-b border-border px-4">
          <h2 className="text-sm font-semibold">{title}</h2>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("close")}
            onClick={onClose}
            icon={<X className="size-4" />}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </>
  );
}
