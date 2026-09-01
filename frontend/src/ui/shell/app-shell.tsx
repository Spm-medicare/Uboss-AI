"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { fetchTaskCounts } from "@/lib/api/tasks";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { useSidebar } from "@/lib/shell/use-sidebar";
import { ErrorState, LoadingState } from "@/ui/states";
import { AccountFooter } from "@/ui/shell/account";
import { SettingsDialog } from "@/ui/settings/settings-dialog";
import { Sidebar } from "@/ui/shell/sidebar";
import { Topbar } from "@/ui/shell/topbar";

/**
 * The frame every workspace screen sits inside — PLAN §29's layout:
 *
 *     Dark collapsible sidebar + compact top bar + light structured main workspace
 *
 * The shell has the same five states as the routes it contains (AS.4), and they are resolved
 * here rather than in each screen. Two of them are easy to get wrong together:
 *
 * * **Signed out** is not an error. The session ended, or was never there; the answer is the
 *   sign-in form, not a message about something going wrong.
 * * **Unreachable** is not signed out. Sending someone to a sign-in form they cannot submit
 *   turns "the API is down" into "your password stopped working", which is the version they
 *   will phone about.
 */
export function AppShell({
  title,
  breadcrumb,
  action,
  children,
}: {
  title: string;
  breadcrumb?: { label: string; href: string }[];
  action?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("shell");
  const router = useRouter();
  const { user, isLoading, isSignedOut, error } = useSession();
  const sidebar = useSidebar();
  const pathname = usePathname();
  //  The path the drawer was opened on. Navigating changes `pathname`, so the drawer closes
  //  without an effect — leaving it open over the screen a person just chose is the single most
  //  common bug in a mobile shell, and an effect that closed it would render the page twice.
  const [openedAt, setOpenedAt] = useState<string | null>(null);
  //  §13's Settings, as a panel over whatever somebody was doing. The state lives here because two
  //  controls open it — the header menu and the sidebar row — and a shared panel needs one owner.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const drawerOpen = openedAt === pathname;

  //  The one number the shell itself shows: how much work is waiting on this person. Fetched
  //  here rather than inside the sidebar because the sidebar is rendered twice on small screens
  //  — once in the drawer — and two components asking would be two requests for one answer.
  //  A failure draws no badge at all: an invented zero would say "nothing is waiting on you",
  //  which is a statement, not an absence.
  const todo = useQuery({
    queryKey: ["tasks", "counts"],
    queryFn: ({ signal }) => fetchTaskCounts(signal),
    enabled: Boolean(user),
  });

  useEffect(() => {
    if (isSignedOut) router.replace("/sign-in");
  }, [isSignedOut, router]);

  if (error) {
    return (
      <main id="main" tabIndex={-1} className="grid min-h-dvh place-items-center bg-background px-6">
        <ErrorState error={error} onRetry={() => router.refresh()} />
      </main>
    );
  }

  if (isLoading || !user) {
    return (
      <main
        id="main"
        //  Focusable by the skip link, but not in the tab order. Without `tabIndex={-1}` the
        //  link scrolls the page and leaves focus at the top, so the next Tab goes back through
        //  the whole navigation — exactly what the link is there to skip.
        tabIndex={-1}
        className="grid min-h-dvh place-items-center bg-background px-6"
        aria-busy
      >
        <LoadingState label={t("loadingWorkspace")} />
      </main>
    );
  }

  const sidebarElement = (
    <Sidebar
      user={user}
      collapsed={sidebar.collapsed}
      onToggle={sidebar.toggle}
      ready={sidebar.ready}
      footer={<AccountFooter collapsed={sidebar.collapsed} />}
      onOpenSettings={() => setSettingsOpen(true)}
      {...(todo.data ? { counts: { todo: todo.data.mine_open } } : {})}
    />
  );

  return (
    <div className="flex min-h-dvh bg-background text-foreground">
      {/*  Fixed rather than in flow, so the main column scrolls on its own and the navigation
          stays put on a long list. */}
      <div className="hidden shrink-0 lg:block">
        <div className="fixed inset-y-0 left-0">{sidebarElement}</div>
        <div
          aria-hidden
          className={cn(
            sidebar.collapsed
              ? "w-[var(--ub-sidebar-collapsed)]"
              : "w-[var(--ub-sidebar-expanded)]",
            sidebar.ready && "transition-[width] duration-200 ease-[var(--ease-standard)]",
            "motion-reduce:transition-none",
          )}
        />
      </div>

      {/*  §3: "Mobile/tablet uses a dismissible drawer." Below `lg` the sidebar is not on the
          page at all until it is asked for. */}
      {drawerOpen ? (
        <MobileDrawer onClose={() => setOpenedAt(null)} label={t("navigation")}>
          {sidebarElement}
        </MobileDrawer>
      ) : null}

      {/*  Over the top of the screen, not instead of it. `/settings` is still a real route for a
          link somebody sends; this is what the gear opens. */}
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} /> : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          title={title}
          {...(breadcrumb ? { breadcrumb } : {})}
          {...(action ? { action } : {})}
          timeZone={user.timezone}
          user={user}
          onOpenNavigation={() => setOpenedAt(pathname)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        {/*  **No cap, and that is the fix.** Every screen used to set its own `max-w-7xl` or
            `max-w-5xl`, which is why a wide monitor — or a zoomed-out window — showed a narrow
            column marooned in white space. Replacing five caps with one did not solve it: a
            measured pass at 3840px found the content filling 49% of the window, because any
            fixed number that is generous on a laptop is a ribbon on a 4K display.

            So width is the *content's* responsibility, at the only place that knows what the
            content is. Card grids use `repeat(auto-fill, minmax(…, 1fr))` and gain columns at
            whatever width they are given; prose sets `max-w-prose`, because a reading measure
            belongs to the text and not to the screen. One rule, no breakpoints, right at 390px
            and at 3840px. */}
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 sm:px-6 sm:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}

function MobileDrawer({
  onClose,
  label,
  children,
}: {
  onClose: () => void;
  label: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    //  Focus moves into the drawer, so the next Tab is inside the navigation rather than back at
    //  the top of the page a person cannot see. Without this the drawer is openable by keyboard
    //  and unusable by it.
    panel.current?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    //  The page behind must not scroll while the drawer is over it — a person swiping to dismiss
    //  otherwise scrolls the content they cannot see.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <>
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-40 bg-black/40 lg:hidden" />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className="fixed inset-y-0 left-0 z-50 focus-visible:outline-none lg:hidden"
      >
        {children}
      </div>
    </>
  );
}
