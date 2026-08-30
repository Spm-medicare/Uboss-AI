"use client";

import { useMutation } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { Mail, MailCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { fetchSignInMethods, requestPasswordReset } from "@/lib/api/sign-in-methods";
import { Alert, Button, Field } from "@/ui";
import { AuthInput } from "@/ui/auth/auth-input";
import { AuthShell } from "@/ui/auth/auth-shell";

/**
 * Ask for a reset link.
 *
 * Two rules from 1.2.6 shape everything on this screen, and they pull in opposite directions:
 *
 * * **The answer must be identical whether or not the account exists.** So the confirmation never
 *   says "we found your account" or "check your inbox" — it says what it can honestly say, which
 *   is that *if* the address is registered, a link is on its way.
 * * **It must never say "email sent" unless an email was accepted for delivery.** The server
 *   reports `delivery: unavailable` when no mail provider is configured, and this screen renders
 *   that as what it is — a fact about the system, not about the account, so saying it plainly
 *   leaks nothing.
 *
 * The second is checked *before* the form as well: when the deployment cannot send mail at all,
 * the form is not offered, because submitting it would achieve nothing.
 */
export default function ForgotPasswordPage() {
  const t = useTranslations("recovery");
  //  The address field is the same field the sign-in screen draws, so it borrows the same
  //  placeholder rather than inventing a second wording for one box.
  const tSignIn = useTranslations("signIn");
  const [email, setEmail] = useState("");

  const methods = useQuery({
    queryKey: ["sign-in-methods"],
    queryFn: ({ signal }) => fetchSignInMethods(signal),
    staleTime: 5 * 60 * 1000,
  });

  const ask = useMutation({
    mutationFn: () => requestPasswordReset(email.trim()),
  });

  const canSend = methods.data?.canSendEmail ?? true;

  return (
    <AuthShell
      title={t("forgotTitle")}
      subtitle={t("forgotSubtitle")}
      back={{ href: "/sign-in", label: t("backToSignIn") }}
    >
      {ask.data ? (
        <div className="space-y-4">
          {ask.data.delivery === "queued" ? (
            <Alert tone="success" title={t("sentTitle")}>
              {/*  Deliberately conditional. Confirming that the address is registered is the one
                  thing this screen must never do. */}
              {t("sentBody", { email: email.trim() })}
            </Alert>
          ) : (
            <Alert tone="warning" title={t("cannotSendTitle")}>
              {t("cannotSendBody")}
            </Alert>
          )}
          <Button variant="secondary" block onClick={() => ask.reset()}>
            {t("tryAnotherAddress")}
          </Button>
        </div>
      ) : !canSend ? (
        <div className="space-y-4">
          <Alert tone="warning" title={t("cannotSendTitle")}>
            {t("cannotSendBody")}
          </Alert>
          <p className="text-sm text-muted-foreground">{t("askAdministrator")}</p>
        </div>
      ) : (
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (email.trim()) ask.mutate();
          }}
        >
          {/*  A failed request renders as a failure. Never a confirmation that did not happen. */}
          {ask.isError ? (
            <Alert tone="danger">
              {ask.error instanceof Error ? ask.error.message : t("failed")}
            </Alert>
          ) : null}

          <Field label={t("email")} htmlFor="forgot-email" required>
            {(field) => (
              <AuthInput
                {...field}
                type="email"
                icon={<Mail className="size-4" />}
                autoComplete="username"
                autoFocus
                placeholder={tSignIn("emailPlaceholder")}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            )}
          </Field>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            busy={ask.isPending}
            disabled={!email.trim()}
            icon={<MailCheck className="size-4" />}
          >
            {t("sendLink")}
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
