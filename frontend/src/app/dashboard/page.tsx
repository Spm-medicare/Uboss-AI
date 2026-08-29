"use client";

import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession, useSignOut } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";

/**
 * The first screen inside a workspace.
 *
 * Deliberately bare. The sidebar, top bar and Copilot drawer are the next step of the build, and
 * a placeholder shell would only have to be torn out. What is here is real: it comes from the
 * signed-in session and nothing on it is invented.
 */
export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const tCommon = useTranslations("common");
  const tRoot = useTranslations("root");
  const router = useRouter();
  const { user, isLoading, isSignedOut, error } = useSession();
  const signOut = useSignOut();

  useEffect(() => {
    if (isSignedOut) router.replace("/sign-in");
  }, [isSignedOut, router]);

  if (error) {
    return (
      <main id="main" className="grid min-h-dvh place-items-center px-6">
        <div className="max-w-sm text-center">
          <h1 className="text-lg font-semibold">{tRoot("notRespondingTitle")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
        </div>
      </main>
    );
  }

  if (isLoading || !user) {
    return (
      <main id="main" className="grid min-h-dvh place-items-center px-6" aria-busy>
        <p className="text-sm text-muted-foreground">{tRoot("loadingWorkspace")}</p>
      </main>
    );
  }

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-4xl items-center justify-between gap-4 px-6">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{user.workspace_name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {user.display_name}
              {user.job_title ? ` · ${user.job_title}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={async () => {
              await signOut.mutateAsync();
              router.replace("/sign-in");
            }}
            disabled={signOut.isPending}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border",
              "px-2.5 py-1.5 text-xs font-medium transition-colors duration-150",
              "hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            <LogOut aria-hidden className="size-3.5" />
            {signOut.isPending ? tCommon("signingOut") : tCommon("signOut")}
          </button>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-4xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("welcome", { name: user.display_name.split(" ")[0] ?? user.display_name })}
        </h1>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          {t("nothingYet")}
        </p>

        <section className="mt-8" aria-labelledby="access-heading">
          <h2 id="access-heading" className="text-sm font-semibold">
            {t("accessHeading")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("accessSubtitle")}
          </p>

          <dl className="mt-3 divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
            <Row label={t("roles")} value={user.roles.join(", ") || tCommon("none")} />
            <Row
              label={t("youCan")}
              value={user.actions.map(readable).join(" · ") || t("nothingYouCan")}
            />
            <Row label={t("timeZone")} value={user.timezone} />
            <Row
              label={t("hierarchyPosition")}
              value={user.org_node_id ? t("placed") : t("notPlaced")}
            />
          </dl>
        </section>
      </main>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 px-5 py-3.5 sm:flex-row sm:items-baseline sm:gap-6">
      <dt className="w-44 shrink-0 text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{value}</dd>
    </div>
  );
}

/** `edit_draft` reads badly on screen; "edit draft" does not. */
function readable(action: string): string {
  return action.replace(/_/g, " ");
}
