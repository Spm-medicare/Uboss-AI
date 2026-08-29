"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/lib/auth/use-session";
import { ErrorState, LoadingState } from "@/ui";

/**
 * The front door.
 *
 * Sends a signed-in person to their workspace and everyone else to the sign-in form. It renders
 * a waiting state rather than guessing, because guessing wrong means either bouncing someone
 * out of a valid session or showing an empty workspace to someone who is not in one.
 */
export default function RootPage() {
  const t = useTranslations("root");
  const router = useRouter();
  const { user, isLoading, isSignedOut, error } = useSession();

  useEffect(() => {
    if (isLoading) return;
    router.replace(user ? "/dashboard" : "/sign-in");
  }, [isLoading, user, router]);

  //  The API is unreachable or broken — a different thing from being signed out, and it must
  //  not send someone to a sign-in form that cannot work either.
  if (error) {
    return (
      <main id="main" className="grid min-h-dvh place-items-center bg-background px-6">
        <ErrorState error={error} onRetry={() => router.refresh()} />
      </main>
    );
  }

  return (
    <main
      id="main"
      className="grid min-h-dvh place-items-center bg-background px-6"
      aria-busy={isLoading}
    >
      <LoadingState
        label={isSignedOut ? t("takingYouToSignIn") : t("loadingWorkspace")}
      />
    </main>
  );
}
