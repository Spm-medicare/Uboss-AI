"use client";

import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { resetPassword } from "@/lib/api/sign-in-methods";
import { Alert, Button, Spinner } from "@/ui";
import { AuthShell } from "@/ui/auth/auth-shell";
import { PasswordFields, isSubmittable } from "@/ui/auth/password-fields";

/**
 * Set a new password from a reset link.
 *
 * **Completing this signs the account out everywhere**, in every workspace — the server does it
 * and the screen says so *before* the button rather than after, because somebody resetting a
 * password on a shared machine deserves to know their phone is about to be signed out too.
 *
 * A used or expired token is not an error to apologise for: it is the single-use rule working.
 * The message says so and offers the way forward, which is a new link.
 */
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ResetPassword />
    </Suspense>
  );
}

function Loading() {
  return (
    <main className="grid min-h-dvh place-items-center">
      <Spinner />
    </main>
  );
}

function ResetPassword() {
  const t = useTranslations("recovery");
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const reset = useMutation({
    mutationFn: () => resetPassword(token, password),
  });

  if (!token) {
    return (
      <AuthShell
        title={t("resetTitle")}
        back={{ href: "/sign-in", label: t("backToSignIn") }}
      >
        <Alert tone="warning" title={t("noTokenTitle")}>
          {t("noTokenBody")}
        </Alert>
      </AuthShell>
    );
  }

  if (reset.isSuccess) {
    return (
      <AuthShell title={t("resetDoneTitle")}>
        <div className="space-y-4">
          <Alert tone="success" title={t("resetDoneHeading")}>
            {t("resetDoneBody")}
          </Alert>
          <Link href="/sign-in" className="block">
            <Button variant="primary" size="lg" block icon={<CheckCircle2 className="size-4" />}>
              {t("goToSignIn")}
            </Button>
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={t("resetTitle")}
      subtitle={t("resetSubtitle")}
      back={{ href: "/sign-in", label: t("backToSignIn") }}
    >
      <form
        className="space-y-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (isSubmittable(password, confirmation)) reset.mutate();
        }}
      >
        {reset.isError ? (
          <Alert tone="danger">
            {reset.error instanceof Error ? reset.error.message : t("failed")}
          </Alert>
        ) : null}

        <PasswordFields
          password={password}
          confirmation={confirmation}
          disabled={reset.isPending}
          onPassword={setPassword}
          onConfirmation={setConfirmation}
        />

        {/*  Said before the button, not after. Somebody resetting on a shared machine should know
            their other devices are about to be signed out. */}
        <Alert tone="info">{t("willSignOutEverywhere")}</Alert>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          block
          busy={reset.isPending}
          disabled={!isSubmittable(password, confirmation)}
          icon={<KeyRound className="size-4" />}
        >
          {t("setNewPassword")}
        </Button>
      </form>
    </AuthShell>
  );
}
