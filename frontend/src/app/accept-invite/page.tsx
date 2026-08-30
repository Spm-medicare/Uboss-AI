"use client";

import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { acceptInvite } from "@/lib/api/sign-in-methods";
import { Alert, Button, Field, Input, Spinner } from "@/ui";
import { AuthShell } from "@/ui/auth/auth-shell";
import { PasswordFields, isSubmittable } from "@/ui/auth/password-fields";

/**
 * Accepting an invitation — the only way an account gets its first password here.
 *
 * **This is not self-service registration.** Somebody with the authority created the account and
 * its membership; this is the invited person choosing a password. Creating a workspace from a
 * sign-up form would be company onboarding — decision `0B.3`, which has not been taken — so there
 * is no such screen, and this one says where an invitation comes from rather than leaving
 * somebody to wonder why they cannot simply register.
 */
export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<Loading />}>
      <AcceptInvite />
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

function AcceptInvite() {
  const t = useTranslations("recovery");
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const accept = useMutation({
    mutationFn: () => acceptInvite(token, password, displayName.trim() || undefined),
  });

  if (!token) {
    return (
      <AuthShell
        title={t("inviteTitle")}
        back={{ href: "/sign-in", label: t("backToSignIn") }}
      >
        <div className="space-y-4">
          <Alert tone="warning" title={t("noInviteTitle")}>
            {t("noInviteBody")}
          </Alert>
          {/*  The honest answer to "why can I not just sign up". Silence here reads as a missing
              feature rather than a deliberate boundary. */}
          <p className="text-sm text-muted-foreground">{t("howToGetAccess")}</p>
        </div>
      </AuthShell>
    );
  }

  if (accept.isSuccess) {
    return (
      <AuthShell title={t("inviteDoneTitle")}>
        <div className="space-y-4">
          <Alert tone="success" title={t("inviteDoneHeading")}>
            {t("inviteDoneBody")}
          </Alert>
          <Link href="/sign-in" className="block">
            <Button
              variant="primary"
              size="lg"
              block
              icon={<CheckCircle2 className="size-4" />}
            >
              {t("goToSignIn")}
            </Button>
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title={t("inviteTitle")} subtitle={t("inviteSubtitle")}>
      <form
        className="space-y-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (isSubmittable(password, confirmation)) accept.mutate();
        }}
      >
        {accept.isError ? (
          <Alert tone="danger">
            {accept.error instanceof Error ? accept.error.message : t("failed")}
          </Alert>
        ) : null}

        <Field label={t("displayName")} htmlFor="display-name" hint={t("displayNameHint")}>
          {(field) => (
            <Input
              {...field}
              autoComplete="name"
              autoFocus
              disabled={accept.isPending}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          )}
        </Field>

        <PasswordFields
          password={password}
          confirmation={confirmation}
          disabled={accept.isPending}
          onPassword={setPassword}
          onConfirmation={setConfirmation}
        />

        <Button
          type="submit"
          variant="primary"
          size="lg"
          block
          busy={accept.isPending}
          disabled={!isSubmittable(password, confirmation)}
          icon={<UserPlus className="size-4" />}
        >
          {t("acceptInvite")}
        </Button>
      </form>
    </AuthShell>
  );
}
