"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, Mail, User } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { ApiError, NetworkError } from "@/lib/api/errors";
import { signUp, type SignUpInput } from "@/lib/api/sign-up";
import { SESSION_QUERY_KEY } from "@/lib/auth/use-session";
import { Alert, Button, Field } from "@/ui";
import { AuthInput } from "@/ui/auth/auth-input";
import { PasswordFields, isSubmittable } from "@/ui/auth/password-fields";

/**
 * Creating an account, and the workspace it lives in, in one step.
 *
 * **Four boxes, not eight.** Name, work email, workspace name, password. Everything else a
 * workspace needs — its org tree, its roles, its objectives — is designed inside the product by
 * somebody who can see what they are configuring, not guessed at on a form by somebody who has
 * not been in yet.
 *
 * **No workspace URL field.** The slug is derived from the workspace name on the server. Asking
 * for it here would be asking somebody to invent a URL segment before they know what the product
 * does with it, and every one they typed would be one they could get wrong.
 *
 * **The refusal is deliberately unhelpful, and that is the design.** A taken address and a taken
 * workspace name come back as one sentence, because two distinguishable messages would let
 * anybody with the form enumerate which addresses are registered. The server decides this; this
 * component only renders what it said.
 */
export function CreateAccount({
  onCreated,
  providers,
}: {
  onCreated: () => void;
  /** The OAuth row, passed in so the page owns the provider state for both tabs. */
  providers?: ReactNode;
}) {
  const t = useTranslations("signUp");
  const queryClient = useQueryClient();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const create = useMutation({
    mutationFn: (input: SignUpInput) => signUp(input),
    onSuccess: (result) => {
      //  Seeded from the response, exactly as the sign-in path does, so the dashboard does not
      //  flash a loading state for a session that was just handed to us.
      queryClient.setQueryData(SESSION_QUERY_KEY, result.user);
      onCreated();
    },
  });

  const filled =
    displayName.trim().length > 0 &&
    email.trim().length > 0 &&
    workspaceName.trim().length > 0;
  const ready = filled && isSubmittable(password, confirmation);

  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready || create.isPending) return;
        create.mutate({
          display_name: displayName.trim(),
          email: email.trim(),
          workspace_name: workspaceName.trim(),
          password,
        });
      }}
    >
      <CreateAccountError error={create.error} />

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("name")} htmlFor="display-name" required>
          {(field) => (
            <AuthInput
              {...field}
              icon={<User className="size-4" />}
              autoComplete="name"
              autoFocus
              disabled={create.isPending}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder={t("namePlaceholder")}
            />
          )}
        </Field>

        <Field label={t("email")} htmlFor="email" required>
          {(field) => (
            <AuthInput
              {...field}
              type="email"
              icon={<Mail className="size-4" />}
              autoComplete="username"
              disabled={create.isPending}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder={t("emailPlaceholder")}
            />
          )}
        </Field>
      </div>

      {/*  The hint is under the field because it changes what the person types: this name is
          what colleagues will see in the workspace switcher, and it is not easily changed
          later. Saying so before they type beats a rename screen afterwards. */}
      <Field
        label={t("workspace")}
        htmlFor="workspace-name"
        hint={t("workspaceHint")}
        required
      >
        {(field) => (
          <AuthInput
            {...field}
            icon={<Building2 className="size-4" />}
            autoComplete="organization"
            disabled={create.isPending}
            value={workspaceName}
            onChange={(event) => setWorkspaceName(event.target.value)}
            placeholder={t("workspacePlaceholder")}
          />
        )}
      </Field>

      <PasswordFields
        password={password}
        confirmation={confirmation}
        onPassword={setPassword}
        onConfirmation={setConfirmation}
        disabled={create.isPending}
        passwordLabel={t("password")}
      />

      <Button
        type="submit"
        variant="primary"
        size="lg"
        block
        //  Disabled rather than hidden, and only on facts this side can be sure of: an empty
        //  box and two passwords that differ. Everything else the server decides.
        disabled={!ready}
        busy={create.isPending}
        className="h-12 text-[0.9375rem]"
      >
        {create.isPending ? t("creating") : t("create")}
        {create.isPending ? null : <ArrowRight aria-hidden className="ml-1.5 size-4" />}
      </Button>

      <p className="text-center text-xs leading-relaxed text-muted-foreground">
        {t("ownerNote")}
      </p>

      {providers ? <div className="pt-1">{providers}</div> : null}
    </form>
  );
}

/**
 * What went wrong, in the server's words where it gave any.
 *
 * A refused sign-up and an unreachable API are different problems with different fixes, so they
 * get different messages. Telling somebody the workspace name is taken when the network is down
 * sends them to invent a new name for no reason.
 */
function CreateAccountError({ error }: { error: Error | null }) {
  const t = useTranslations("signUp");

  if (!error) return null;
  if (error instanceof NetworkError) {
    return <Alert tone="offline">{t("offline")}</Alert>;
  }
  return (
    <Alert tone="danger">{error instanceof ApiError ? error.message : t("failed")}</Alert>
  );
}
