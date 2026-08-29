"use client";

import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession, useSignOut } from "@/lib/auth/use-session";
import {
  Button,
  Card,
  DescriptionList,
  DescriptionRow,
  ErrorState,
  LoadingState,
} from "@/ui";

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
        <ErrorState error={error} onRetry={() => router.refresh()} />
      </main>
    );
  }

  if (isLoading || !user) {
    return (
      <main id="main" className="grid min-h-dvh place-items-center px-6" aria-busy>
        <LoadingState label={tRoot("loadingWorkspace")} />
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
          <Button
            size="sm"
            className="shrink-0"
            icon={<LogOut className="size-3.5" />}
            busy={signOut.isPending}
            onClick={async () => {
              await signOut.mutateAsync();
              router.replace("/sign-in");
            }}
          >
            {signOut.isPending ? tCommon("signingOut") : tCommon("signOut")}
          </Button>
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
          <p className="mt-1 text-sm text-muted-foreground">{t("accessSubtitle")}</p>

          <Card className="mt-3 overflow-hidden">
            <DescriptionList>
              <DescriptionRow label={t("roles")}>
                {user.roles.join(", ") || tCommon("none")}
              </DescriptionRow>
              <DescriptionRow label={t("youCan")}>
                {user.actions.map(readable).join(" · ") || t("nothingYouCan")}
              </DescriptionRow>
              <DescriptionRow label={t("timeZone")}>{user.timezone}</DescriptionRow>
              <DescriptionRow label={t("hierarchyPosition")}>
                {user.org_node_id ? t("placed") : t("notPlaced")}
              </DescriptionRow>
            </DescriptionList>
          </Card>
        </section>
      </main>
    </div>
  );
}

/** `edit_draft` reads badly on screen; "edit draft" does not. */
function readable(action: string): string {
  return action.replace(/_/g, " ");
}
