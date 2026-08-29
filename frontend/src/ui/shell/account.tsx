"use client";

import { Building2, LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

import type { CurrentUser } from "@/lib/api/auth";
import { useSignOut } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { Alert } from "@/ui/alert";
import { Button } from "@/ui/button";

/**
 * §3's sidebar footer: avatar and name, workspace switcher, sign-out.
 *
 * The switcher is the honest part. There is no endpoint that moves a signed-in session to another
 * workspace — sign-in is where a person with more than one chooses, and the challenge that makes
 * that safe is consumed there. So this does what it can actually do and says so: it signs out and
 * returns to the chooser. A control that quietly failed, or one that looked like an instant
 * switch and was not, would be worse than the extra sentence.
 *
 * It is shown to everyone. Whether this person belongs to a second workspace is a cross-tenant
 * fact, and the only cross-tenant read in the product is the one sign-in already makes under a
 * verified user id — `identity.workspaces_for`. Rebinding that inside `/auth/me` to decide
 * whether to draw one button would widen a boundary that exists for a reason. The chooser is
 * where the real list is, and this is the way back to it.
 */
export function AccountFooter({
  user,
  collapsed,
}: {
  user: CurrentUser;
  collapsed: boolean;
}) {
  const t = useTranslations("account");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const signOut = useSignOut();

  async function endSession(next: string) {
    await signOut.mutateAsync();
    router.replace(next);
  }

  return (
    <div className="mt-1 border-t border-sidebar-border pt-2">
      <div
        className={cn(
          "flex items-center gap-2.5 rounded-md px-2.5 py-2",
          collapsed && "justify-center px-0",
        )}
      >
        <span
          aria-hidden
          className="grid size-7 shrink-0 place-items-center rounded-full bg-sidebar-active text-xs font-semibold"
        >
          {initials(user.display_name)}
        </span>
        {!collapsed ? (
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-sm">{user.display_name}</span>
            {user.job_title ? (
              <span className="block truncate text-xs text-sidebar-muted">
                {user.job_title}
              </span>
            ) : null}
          </span>
        ) : null}
      </div>

      {signOut.error ? (
        <Alert tone="danger" className="mx-1 mb-1.5">
          {signOut.error.message}
        </Alert>
      ) : null}

      <div className={cn("space-y-0.5", collapsed && "flex flex-col items-center")}>
        <FooterAction
          collapsed={collapsed}
          label={t("switchWorkspace")}
          hint={t("switchWorkspaceHint")}
          icon={<Building2 className="size-4" />}
          busy={signOut.isPending}
          onClick={() => void endSession("/sign-in")}
        />

        <FooterAction
          collapsed={collapsed}
          label={signOut.isPending ? tCommon("signingOut") : tCommon("signOut")}
          icon={<LogOut className="size-4" />}
          busy={signOut.isPending}
          onClick={() => void endSession("/sign-in")}
        />
      </div>
    </div>
  );
}

function FooterAction({
  collapsed,
  label,
  hint,
  icon,
  busy,
  onClick,
}: {
  collapsed: boolean;
  label: string;
  hint?: string;
  icon: React.ReactNode;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      block={!collapsed}
      busy={busy}
      onClick={onClick}
      title={hint ?? label}
      {...(collapsed ? { "aria-label": label } : {})}
      icon={icon}
      className={cn(
        "text-sidebar-muted hover:bg-sidebar-surface hover:text-sidebar-foreground",
        collapsed ? "size-8 px-0" : "justify-start",
      )}
    >
      {collapsed ? null : label}
    </Button>
  );
}

/** Two letters, never an image. There is no avatar upload, so there is nothing to display. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}
