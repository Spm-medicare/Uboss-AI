"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { finishOAuth } from "@/lib/api/sign-in-methods";
import { Alert, Button, Spinner } from "@/ui";
import { AuthShell } from "@/ui/auth/auth-shell";

/**
 * Where a provider sends the browser back.
 *
 * The page does one thing: hand the code and state to the server and go where it says. The PKCE
 * verifier that completes the exchange never existed in this browser, which is the point — an
 * intercepted code is worthless without it.
 *
 * **Every failure lands here as a sentence, not a blank page.** A cancelled sign-in, an expired
 * state, an account nobody has linked: each says what happened and offers somewhere to go, because
 * the alternative is a person watching a spinner that never stops.
 */
export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={<Waiting />}>
      <Callback />
    </Suspense>
  );
}

function Waiting() {
  const t = useTranslations("signIn");
  return (
    <main className="grid min-h-dvh place-items-center gap-3">
      <Spinner />
      <p className="text-sm text-muted-foreground">{t("finishing")}</p>
    </main>
  );
}

function Callback() {
  const t = useTranslations("signIn");
  const router = useRouter();
  const params = useParams<{ provider: string }>();
  const search = useSearchParams();

  const provider = params.provider;
  const code = search.get("code");
  const state = search.get("state");
  //  Providers report a refusal in the query string rather than by failing the redirect.
  const denied = search.get("error");

  const finish = useMutation({
    mutationFn: () => finishOAuth(provider, code ?? "", state ?? ""),
    onSuccess: (result) => {
      const next = typeof result.next === "string" ? result.next : "/dashboard";
      router.replace(next.startsWith("/") ? next : "/dashboard");
    },
  });

  //  Fired once. Without the guard a re-render would replay the exchange, and the state is
  //  single-use — the second attempt would fail and replace a perfectly good session with an
  //  error message.
  const started = useRef(false);
  const run = finish.mutate;
  useEffect(() => {
    if (started.current || denied || !code || !state) return;
    started.current = true;
    run();
  }, [code, state, denied, run]);

  if (denied) {
    return (
      <AuthShell title={t("notCompletedTitle")}>
        <div className="space-y-4">
          <Alert tone="info">{t("cancelled", { provider })}</Alert>
          <BackToSignIn />
        </div>
      </AuthShell>
    );
  }

  if (!code || !state) {
    return (
      <AuthShell title={t("notCompletedTitle")}>
        <div className="space-y-4">
          <Alert tone="warning">{t("missingResponse")}</Alert>
          <BackToSignIn />
        </div>
      </AuthShell>
    );
  }

  if (finish.isError) {
    return (
      <AuthShell title={t("notCompletedTitle")}>
        <div className="space-y-4">
          <Alert tone="danger">
            {finish.error instanceof Error ? finish.error.message : t("failed")}
          </Alert>
          <BackToSignIn />
        </div>
      </AuthShell>
    );
  }

  return <Waiting />;
}

function BackToSignIn() {
  const t = useTranslations("signIn");
  return (
    <Link href="/sign-in" className="block">
      <Button variant="secondary" size="lg" block>
        {t("backToSignIn")}
      </Button>
    </Link>
  );
}
