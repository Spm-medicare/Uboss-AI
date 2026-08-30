"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Lock, Mail } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type { WorkspaceSummary } from "@/lib/api/auth";
import { ApiError, NetworkError } from "@/lib/api/errors";
import { startOAuth } from "@/lib/api/sign-in-methods";
import { useSelectWorkspace, useSignIn } from "@/lib/auth/use-session";
import { Alert, Button, Field } from "@/ui";
import { AuthInput } from "@/ui/auth/auth-input";
import { AuthShell, AuthTabs, ProviderButtons } from "@/ui/auth/auth-shell";
import { CreateAccount } from "@/ui/auth/create-account";

/**
 * The form's own rules, kept deliberately loose.
 *
 * Everything here is about catching an empty box before a round trip. It does not validate the
 * *shape* of an address, because a stricter client rule than the server's would refuse a real
 * account — and because a "that is not a valid address" message tells an attacker which addresses
 * are worth trying, which is the one thing this screen must never do.
 */
//  The message keys, not the messages. `zodResolver` resolves them against the catalogue at
//  render time, so a validation message is translated like every other string.
const schema = z.object({
  email: z.string().trim().min(1, "signIn.emailRequired"),
  password: z.string().min(1, "signIn.passwordRequired"),
});

type FormValues = z.infer<typeof schema>;

export default function SignInPage() {
  const t = useTranslations("signIn");
  const tChooser = useTranslations("workspaceChooser");
  const router = useRouter();
  const signIn = useSignIn();
  const selectWorkspace = useSelectWorkspace();

  const [view, setView] = useState<"signin" | "register">("signin");

  // The challenge proves the password was already verified. The password is cleared before this
  // state is shown and is never submitted with the workspace choice.
  const [choice, setChoice] = useState<{
    challenge: string;
    workspaces: WorkspaceSummary[];
  } | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const [provider, setProvider] = useState<string | null>(null);
  const federated = useMutation({
    mutationFn: async (name: string) => {
      setProvider(name);
      //  The server mints the state and the PKCE challenge; this only navigates. A full page load
      //  rather than a router push, because the destination is somebody else's origin.
      window.location.assign(await startOAuth(name));
    },
    onError: () => setProvider(null),
  });

  async function submit(values: FormValues) {
    const result = await signIn.mutateAsync(values);
    if (result.status === "choose_workspace") {
      form.resetField("password");
      setChoice({ challenge: result.challenge, workspaces: result.workspaces });
      return;
    }
    router.replace("/dashboard");
  }

  async function chooseWorkspace(workspace: string) {
    if (!choice) return;
    await selectWorkspace.mutateAsync({ challenge: choice.challenge, workspace });
    router.replace("/dashboard");
  }

  //  Choosing a workspace is its own step, not a third tab: the password is already verified and
  //  going back to the form would mean typing it again for nothing.
  if (choice) {
    return (
      <AuthShell
        eyebrow={tChooser("eyebrow")}
        title={tChooser("title")}
        subtitle={tChooser("subtitle")}
      >
        <WorkspaceChooser
          workspaces={choice.workspaces}
          busy={selectWorkspace.isPending}
          error={selectWorkspace.error}
          onPick={(slug) => void chooseWorkspace(slug)}
          onBack={() => {
            setChoice(null);
            signIn.reset();
            selectWorkspace.reset();
          }}
        />
      </AuthShell>
    );
  }

  const tabs = (
    <AuthTabs
      value={view}
      onChange={(next) => {
        setView(next);
        signIn.reset();
        federated.reset();
      }}
    />
  );

  if (view === "register") {
    return (
      <AuthShell
        eyebrow={t("registerEyebrow")}
        title={t("registerTitle")}
        subtitle={t("registerSubtitle")}
        tabs={tabs}
      >
        <CreateAccount
          onCreated={() => router.replace("/dashboard")}
          providers={
            <ProviderButtons
              purpose="register"
              busyProvider={provider}
              error={federated.error as Error | null}
              onStart={(name) => federated.mutate(name)}
            />
          }
        />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow={t("eyebrow")}
      title={t("title")}
      subtitle={t("subtitle")}
      tabs={tabs}
    >
      <SignInError error={signIn.error} />

      <form
        className="space-y-5"
        onSubmit={form.handleSubmit((values) => submit(values))}
        noValidate
      >
        <Field
          label={t("email")}
          error={form.formState.errors.email?.message}
          htmlFor="email"
          required
        >
          {(field) => (
            <AuthInput
              {...form.register("email")}
              {...field}
              type="email"
              icon={<Mail className="size-4" />}
              autoComplete="username"
              autoFocus
              placeholder={t("emailPlaceholder")}
            />
          )}
        </Field>

        <Field
          label={t("password")}
          error={form.formState.errors.password?.message}
          htmlFor="password"
          required
          action={
            <Link
              href="/forgot-password"
              className="text-sm font-medium text-primary underline-offset-4 transition-colors duration-150 hover:underline motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]"
            >
              {t("forgotPassword")}
            </Link>
          }
        >
          {(field) => (
            <AuthInput
              {...form.register("password")}
              {...field}
              type="password"
              reveal
              icon={<Lock className="size-4" />}
              autoComplete="current-password"
            />
          )}
        </Field>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          block
          busy={signIn.isPending}
          className="h-12 text-[0.9375rem]"
        >
          {signIn.isPending ? t("submitting") : t("submit")}
          {signIn.isPending ? null : (
            <ArrowRight aria-hidden className="ml-1.5 size-4" />
          )}
        </Button>
      </form>

      {/*  Only the providers this deployment has credentials for. A button that cannot complete
          a sign-in is a control that does not do what it says, so it is not drawn. */}
      <div className="mt-7">
        <ProviderButtons
          busyProvider={provider}
          error={federated.error as Error | null}
          onStart={(name) => federated.mutate(name)}
        />
      </div>
    </AuthShell>
  );
}

function WorkspaceChooser({
  workspaces,
  busy,
  error,
  onPick,
  onBack,
}: {
  workspaces: WorkspaceSummary[];
  busy: boolean;
  error: Error | null;
  onPick: (slug: string) => void;
  onBack: () => void;
}) {
  //  The heading is the shell's; these are the chooser's own words.
  const t = useTranslations("workspaceChooser");

  return (
    <>
      <SignInError error={error} />

      <ul className="space-y-2.5">
        {workspaces.map((workspace) => (
          <li key={workspace.slug}>
            {/*  The whole card is one choice, so the target is the card and not a link inside it.
                `Button` carries the focus ring and the disabled behaviour; the layout is the only
                thing this screen adds. */}
            <Button
              variant="secondary"
              block
              disabled={busy}
              onClick={() => onPick(workspace.slug)}
              className="h-auto justify-between rounded-xl border border-border bg-card px-4 py-3.5 text-left hover:bg-accent"
            >
              <span>
                <span className="block text-sm font-semibold">{workspace.name}</span>
                <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                  {t("signingInAs", { name: workspace.display_name })}
                </span>
              </span>
              <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            </Button>
          </li>
        ))}
      </ul>

      <Button
        variant="ghost"
        size="sm"
        onClick={onBack}
        className="mt-6 px-0 text-muted-foreground underline underline-offset-4 hover:bg-transparent hover:text-foreground"
      >
        {t("useAnotherAccount")}
      </Button>
    </>
  );
}

/**
 * What went wrong, in the words the server used.
 *
 * A network failure and a refused credential are different things and get different messages —
 * telling somebody their password is wrong when the API is down sends them to reset a password
 * that was never the problem.
 */
function SignInError({ error }: { error: Error | null }) {
  const t = useTranslations("signIn");

  if (!error) return null;
  if (error instanceof NetworkError) {
    return (
      <Alert tone="offline" className="mb-5">
        {t("offline")}
      </Alert>
    );
  }
  return (
    <Alert tone="danger" className="mb-5">
      {error instanceof ApiError ? error.message : t("failed")}
    </Alert>
  );
}
