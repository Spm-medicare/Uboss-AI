"use client";

import { useTranslations } from "next-intl";

import { useSession } from "@/lib/auth/use-session";
import {
  Card,
  DescriptionList,
  DescriptionRow,
  LoadingState,
} from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * The first screen inside a workspace.
 *
 * PLAN §4 defines the Dashboard as pending tasks, approvals waiting, running and failed Agents,
 * upcoming schedules and recent outputs — *"Every metric is clickable, defined and timestamped."*
 * None of those exist yet: there are no tasks, no approvals and no runs in the product, so there
 * is nothing to count.
 *
 * The alternative is a wall of cards showing zeros or, worse, sample figures. `CLAUDE.md` is
 * blunt about which of those matters: *"Never display a value the backend did not return."* A
 * fabricated "3 approvals waiting" is not a placeholder, it is a number somebody will act on.
 * So what is here is what the session actually returned, and the metrics arrive with the
 * features that produce them.
 */
export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const tCommon = useTranslations("common");
  const { user } = useSession();

  return (
    <AppShell title={t("title")}>
      {user ? (
        <div className="mx-auto max-w-4xl">
          <h2 className="text-2xl font-semibold tracking-tight">
            {t("welcome", {
              name: user.display_name.split(" ")[0] ?? user.display_name,
            })}
          </h2>
          <p className="mt-2 max-w-prose text-sm text-muted-foreground">
            {t("nothingYet")}
          </p>

          <section className="mt-8" aria-labelledby="access-heading">
            <h3 id="access-heading" className="text-sm font-semibold">
              {t("accessHeading")}
            </h3>
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
        </div>
      ) : (
        //  Unreachable in practice — the shell resolves loading, error and signed-out above this
        //  point. Kept so the component is total rather than relying on that ordering.
        <LoadingState />
      )}
    </AppShell>
  );
}

/** `edit_draft` reads badly on screen; "edit draft" does not. */
function readable(action: string): string {
  return action.replace(/_/g, " ");
}
