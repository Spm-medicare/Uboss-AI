"use client";

import { Bell, Menu, Search, Sparkles, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Alert } from "@/ui/alert";
import { Button } from "@/ui/button";
import { EmptyState } from "@/ui/states";

/**
 * The compact top bar of PLAN §3:
 *
 *     Breadcrumb/title | Global search | Context action | Notifications | UBOSS Copilot
 *
 * Three of those five have no backend yet, and this is where a shell usually starts lying — a
 * search box that silently returns nothing, a bell with a hard-coded "3", a Copilot that replies
 * from a fixture. `docs/delivery/WORK_BREAKDOWN.md` is explicit about the alternative: *"Search
 * shows an honest unavailable state until Gate 7. Notifications and Copilot show governed empty
 * states. No fake activity, no invented counts."*
 *
 * So the search field is disabled and says why, and the bell carries no count until something
 * real can produce one. An empty bell is accurate. A bell showing `0` would also be accurate but
 * would claim the number is known; it is not.
 */
export function Topbar({
  title,
  breadcrumb,
  action,
  onOpenNavigation,
}: {
  title: string;
  /** Ancestors, nearest last. The current screen is the `title` and is never repeated here. */
  breadcrumb?: { label: string; href: string }[];
  /** The one context action for this screen — §29's "one clear primary action per screen". */
  action?: ReactNode;
  /** Opens the mobile drawer. Absent on wide screens, where the sidebar is always present. */
  onOpenNavigation: () => void;
}) {
  const t = useTranslations("shell");
  const [drawer, setDrawer] = useState<"notifications" | "copilot" | null>(null);

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
        {breadcrumb && breadcrumb.length > 0 ? (
          <nav aria-label={t("breadcrumb")}>
            <ol className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {breadcrumb.map((crumb) => (
                <li key={crumb.href} className="flex items-center gap-1.5">
                  <a
                    href={crumb.href}
                    className="truncate rounded-sm underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]"
                  >
                    {crumb.label}
                  </a>
                  <span aria-hidden>/</span>
                </li>
              ))}
            </ol>
          </nav>
        ) : null}
        <h1 className="truncate text-sm font-semibold">{title}</h1>
      </div>

      <GlobalSearch />

      {action}

      <Button
        variant="ghost"
        size="sm"
        aria-label={t("notifications")}
        aria-expanded={drawer === "notifications"}
        onClick={() => setDrawer(drawer === "notifications" ? null : "notifications")}
        icon={<Bell className="size-4" />}
      />

      <Button
        variant="ghost"
        size="sm"
        aria-label={t("copilot")}
        aria-expanded={drawer === "copilot"}
        onClick={() => setDrawer(drawer === "copilot" ? null : "copilot")}
        icon={<Sparkles className="size-4" />}
      />

      {drawer ? (
        <Drawer
          title={drawer === "notifications" ? t("notifications") : t("copilot")}
          onClose={() => setDrawer(null)}
        >
          {drawer === "notifications" ? (
            <EmptyState
              title={t("notificationsEmptyTitle")}
              description={t("notificationsEmptyBody")}
            />
          ) : (
            <div className="p-4">
              <Alert tone="info" title={t("copilotUnavailableTitle")}>
                {t("copilotUnavailableBody")}
              </Alert>
            </div>
          )}
        </Drawer>
      ) : null}
    </header>
  );
}

/**
 * Search, before there is anything to search.
 *
 * Disabled and labelled rather than absent: a person looks for a search box, and finding none
 * reads as "this product has no search". Finding one that says it is not connected yet is a
 * smaller and truer thing to say.
 */
function GlobalSearch() {
  const t = useTranslations("shell");

  return (
    <div className="hidden min-w-0 max-w-xs flex-1 md:block">
      <label htmlFor="global-search" className="sr-only">
        {t("search")}
      </label>
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <input
          id="global-search"
          type="search"
          disabled
          placeholder={t("searchUnavailable")}
          title={t("searchUnavailableWhy")}
          className={cn(
            "w-full rounded-md border border-border bg-card py-1.5 pl-8 pr-3 text-sm",
            "placeholder:text-muted-foreground",
            "disabled:cursor-not-allowed disabled:opacity-60",
          )}
        />
      </div>
    </div>
  );
}

/**
 * The right-hand panel §29 calls the "optional right Copilot/help drawer".
 *
 * A dialog, so focus is trapped inside it and Escape closes it. Both are what makes it dismissible
 * for someone using a keyboard, and both are what a `<div>` with an onClick does not give.
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
