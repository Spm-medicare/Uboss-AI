"use client";

import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";

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
export function AccountFooter({ collapsed }: { collapsed: boolean }) {
  const tCommon = useTranslations("common");
  const router = useRouter();
  const signOut = useSignOut();

  async function endSession(next: string) {
    await signOut.mutateAsync();
    router.replace(next);
  }

  return (
    <div
      className={cn(
        collapsed
          //  `contents` so the single row joins the foot's own centred column instead of
          //  starting a second, differently-spaced one inside it.
          ? "contents"
          : "mt-1 border-t border-sidebar-border pt-2",
      )}
    >
      {/*  **The person moved to the top bar.** Their name, their workspace and the way out are
          one menu there — see `header-account.tsx`. What is left here is the single action, so
          that a collapsed rail still has an exit and so the sidebar does not become a second
          place the same three facts are printed.

          *Switch workspace* is gone. It ran `endSession("/sign-in")` — byte for byte what *Sign
          out* ran — so two labels described one behaviour and only a tooltip distinguished them.
          Choosing a workspace happens on the sign-in screen, which is where signing out leads. */}
      {signOut.error ? (
        <Alert tone="danger" className="mx-1 mb-1.5">
          {signOut.error.message}
        </Alert>
      ) : null}

      <div className={cn(collapsed ? "contents" : "space-y-0.5")}>
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

