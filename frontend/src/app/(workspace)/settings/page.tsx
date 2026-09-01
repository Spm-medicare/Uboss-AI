"use client";

import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { useSession } from "@/lib/auth/use-session";
import { QueryStates } from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";
import { CATEGORIES, type SettingsCategory } from "@/ui/settings/catalogue";
import { SettingsPanel } from "@/ui/settings/panel";

/**
 * Settings as a page — for a link somebody sends, and for anybody who types the address.
 *
 * The gear in the header and the row in the sidebar open the **overlay** instead
 * (`settings-dialog.tsx`), because changing your timezone in the middle of something else should not
 * cost you your place. Both render the same `SettingsPanel`: the same screen reached two ways has to
 * be the same screen.
 *
 * Here the open category is a query parameter — `?c=security` — so the link is worth sending and the
 * back button walks the categories rather than leaving Settings entirely.
 */
export default function SettingsPage() {
  const t = useTranslations("settings");

  return (
    <AppShell title={t("title")}>
      {/*  `useSearchParams` needs a Suspense boundary in an app-router client page; without one the
          build fails on prerender rather than at runtime, which is the good kind of failure. */}
      <Suspense fallback={null}>
        <Settings />
      </Suspense>
    </AppShell>
  );
}

function Settings() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, isLoading, error } = useSession();

  const wanted = params.get("c");
  const chosen = CATEGORIES.find((category) => category.id === wanted) ?? CATEGORIES[0]!;

  function open(category: SettingsCategory) {
    //  `replace`, not `push`: seventeen categories clicked through would otherwise be seventeen
    //  entries between here and the screen somebody came from.
    router.replace(`/settings?c=${category.id}`, { scroll: false });
  }

  return (
    <QueryStates isPending={isLoading} error={error} isEmpty={false} emptyTitle="">
      {user ? <SettingsPanel user={user} chosen={chosen} onChoose={open} /> : null}
    </QueryStates>
  );
}
