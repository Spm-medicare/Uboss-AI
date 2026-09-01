"use client";

import { LogOut, Moon, Settings as SettingsIcon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { CurrentUser } from "@/lib/api/auth";
import { useSignOut } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { applyThemeChoice, useTheme } from "@/lib/theme";
import { Alert } from "@/ui/alert";

/**
 * Light or dark, in the top bar.
 *
 * **Two states here, not three.** The sidebar's version offered *System* as well, which is the
 * honest full set — but a header control has room for one glyph, and a three-way cycle behind one
 * icon is a control whose next press nobody can predict. So this switches between light and dark
 * explicitly, and *System* remains available where there is room to label it (Settings, §13's
 * "Appearance and reduced motion").
 *
 * The icon shows what pressing it will *do*, not what is currently on — a sun when the next press
 * gives you light. Both readings are common and neither is more correct; what matters is that the
 * accessible name says which, so nobody has to guess from the picture.
 */
export function ThemeSwitch() {
  const t = useTranslations("appearance");
  const { resolved } = useTheme();
  const next = resolved === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => applyThemeChoice(next)}
      aria-label={t("switchTo", { next: t(next) })}
      title={t("switchTo", { next: t(next) })}
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground",
        "transition-colors duration-150 hover:bg-accent hover:text-foreground",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        "motion-reduce:transition-none",
      )}
    >
      {next === "dark" ? (
        <Moon aria-hidden className="size-4" />
      ) : (
        <Sun aria-hidden className="size-4" />
      )}
    </button>
  );
}

/**
 * The person, in the top bar — their name, their workspace, and the way out.
 *
 * It was at the foot of the sidebar, below a *Workspace* card that repeated the workspace name a
 * second time and above a *Switch workspace* button that did exactly what *Sign out* did. All
 * three are gone: the name lives here, the workspace is a line inside this menu rather than a
 * card of its own, and there is one way to end a session because there was only ever one.
 *
 * A menu rather than a row of buttons, because the top bar is chrome and chrome should be one
 * affordance wide. Escape closes it, a click outside closes it, and focus returns to the trigger —
 * the three things a menu has to do and the three most often left out.
 */
export function HeaderAccount({
  user,
  onOpenSettings,
}: {
  user: CurrentUser;
  onOpenSettings: () => void;
}) {
  const t = useTranslations("account");
  const tCommon = useTranslations("common");
  const signOut = useSignOut();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        //  Focus goes back to what opened the menu. Without this it lands on the document and
        //  the next Tab starts from the top of the page.
        trigger.current?.focus();
      }
    }
    function onPointer(event: MouseEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }

    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  return (
    <div ref={wrapper} className="relative shrink-0">
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((was) => !was)}
        className={cn(
          "flex items-center gap-2 rounded-md py-1 pl-1 pr-1.5",
          "transition-colors duration-150 hover:bg-accent",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
          "motion-reduce:transition-none",
        )}
      >
        <span
          aria-hidden
          className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
        >
          {initials(user.display_name)}
        </span>
        {/*  The name is hidden below `sm` and the avatar carries it — a name in a 360px bar
            leaves no room for the bar. It stays in the accessible name either way. */}
        <span className="hidden max-w-[10rem] truncate text-sm font-medium sm:block">
          {user.display_name}
        </span>
        <span className="sr-only sm:hidden">{user.display_name}</span>
      </button>

      {open ? (
        <div
          role="menu"
          aria-label={t("menu")}
          className={cn(
            "absolute right-0 top-full z-50 mt-1.5 w-64 overflow-hidden rounded-xl",
            "border border-border bg-card shadow-popover",
          )}
        >
          <div className="border-b border-border px-3.5 py-3">
            <p className="truncate text-sm font-medium">{user.display_name}</p>
            {user.job_title ? (
              <p className="truncate text-xs text-muted-foreground">
                {user.job_title}
              </p>
            ) : null}
            {/*  The workspace, as a line of context rather than a card of its own. It answers
                "which workspace am I signed into" at the moment somebody wonders — which is
                when they are looking at their own name. */}
            <p className="mt-1.5 truncate text-xs text-muted-foreground">
              {t("inWorkspace", { workspace: user.workspace_name })}
            </p>
          </div>

          {signOut.error ? (
            <Alert tone="danger" className="m-2">
              {signOut.error.message}
            </Alert>
          ) : null}

          {/*  Settings, from the header — where somebody looking at their own name looks for it.
              §13 gives Settings a page of its own and §3 puts a gear in the top bar; this is that
              gear, inside the menu the name already opens rather than a second icon competing for
              the same forty pixels. The sidebar keeps its row as well: one of the two is muscle
              memory for everybody, and neither is the wrong place to look. */}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              //  A panel over the screen, not a navigation away from it. Changing a timezone in
              //  the middle of something else should not cost somebody their place.
              setOpen(false);
              onOpenSettings();
            }}
            className={cn(
              "flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm",
              "transition-colors duration-150 hover:bg-accent",
              "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              "motion-reduce:transition-none",
            )}
          >
            <SettingsIcon aria-hidden className="size-4 text-muted-foreground" />
            {t("settings")}
          </button>

          <button
            type="button"
            role="menuitem"
            disabled={signOut.isPending}
            onClick={() => {
              //  The redirect is the sign-in screen, which is where a session ends. There is no
              //  second destination, which is why there is no longer a second button.
              void signOut.mutateAsync().then(() => {
                router.replace("/sign-in");
              });
            }}
            className={cn(
              "flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm",
              "transition-colors duration-150 hover:bg-accent disabled:opacity-60",
              "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              "motion-reduce:transition-none",
            )}
          >
            <LogOut aria-hidden className="size-4 text-muted-foreground" />
            {signOut.isPending ? tCommon("signingOut") : tCommon("signOut")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Two letters at most, from the name the workspace knows them by. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0]![0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]![0] ?? "") : "";
  return (first + last).toUpperCase();
}
