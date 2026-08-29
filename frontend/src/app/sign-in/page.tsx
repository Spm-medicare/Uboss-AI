"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle, ArrowRight, Loader2, WifiOff } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type { WorkspaceSummary } from "@/lib/api/auth";
import { ApiError, NetworkError } from "@/lib/api/errors";
import { useSelectWorkspace, useSignIn } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";

/**
 * The form's own rules, kept deliberately loose.
 *
 * Everything here is about catching an empty box before a round trip. It does not validate the
 * *shape* of an address, because a stricter client rule than the server's would refuse a real
 * account — and because a "that is not a valid address" message tells an attacker which
 * addresses are worth trying, which is the one thing this screen must never do.
 */
const schema = z.object({
  email: z.string().trim().min(1, "Enter your email address."),
  password: z.string().min(1, "Enter your password."),
});

type FormValues = z.infer<typeof schema>;

export default function SignInPage() {
  const router = useRouter();
  const signIn = useSignIn();
  const selectWorkspace = useSelectWorkspace();

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

  async function submit(values: FormValues) {
    const result = await signIn.mutateAsync(values);
    if (result.status === "choose_workspace") {
      form.resetField("password");
      setChoice({
        challenge: result.challenge,
        workspaces: result.workspaces,
      });
      return;
    }
    router.replace("/dashboard");
  }

  async function chooseWorkspace(workspace: string) {
    if (!choice) return;
    await selectWorkspace.mutateAsync({
      challenge: choice.challenge,
      workspace,
    });
    router.replace("/dashboard");
  }

  return (
    <main
      id="main"
      className="grid min-h-dvh place-items-center bg-background px-6 py-12"
    >
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-lg bg-primary text-base font-semibold text-primary-foreground">
            U
          </span>
          <div className="leading-tight">
            <p className="text-base font-semibold tracking-tight">UBOSS</p>
            <p className="text-xs text-muted-foreground">
              Governed human and AI work
            </p>
          </div>
        </div>

        {choice ? (
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
        ) : (
          <>
            <h1 className="text-xl font-semibold tracking-tight">Sign in</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Use the address your organisation set you up with.
            </p>

            <SignInError error={signIn.error} />

            <form
              className="mt-6 space-y-4"
              onSubmit={form.handleSubmit((values) => submit(values))}
              noValidate
            >
              <Field
                label="Email"
                error={form.formState.errors.email?.message}
                htmlFor="email"
              >
                <input
                  {...form.register("email")}
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  className={inputClass(!!form.formState.errors.email)}
                />
              </Field>

              <Field
                label="Password"
                error={form.formState.errors.password?.message}
                htmlFor="password"
              >
                <input
                  {...form.register("password")}
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  className={inputClass(!!form.formState.errors.password)}
                />
              </Field>

              <button
                type="submit"
                disabled={signIn.isPending}
                className={cn(
                  "flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5",
                  "text-sm font-medium text-primary-foreground",
                  "transition-colors duration-150 hover:bg-[var(--ub-brand-hover)]",
                  "disabled:cursor-not-allowed disabled:opacity-70",
                )}
              >
                {signIn.isPending ? (
                  <>
                    <Loader2 aria-hidden className="size-4 animate-spin" />
                    Signing in
                  </>
                ) : (
                  "Sign in"
                )}
              </button>
            </form>
          </>
        )}
      </div>
    </main>
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
  return (
    <>
      <h1 className="text-xl font-semibold tracking-tight">Choose a workspace</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Your account belongs to more than one organisation.
      </p>

      <SignInError error={error} />

      <ul className="mt-6 space-y-2">
        {workspaces.map((workspace) => (
          <li key={workspace.slug}>
            <button
              type="button"
              disabled={busy}
              onClick={() => onPick(workspace.slug)}
              className={cn(
                "flex w-full items-center justify-between gap-3 rounded-lg border border-border",
                "bg-card px-4 py-3 text-left transition-colors duration-150",
                "hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60",
              )}
            >
              <span>
                <span className="block text-sm font-medium">{workspace.name}</span>
                <span className="block text-xs text-muted-foreground">
                  Signing in as {workspace.display_name}
                </span>
              </span>
              <ArrowRight aria-hidden className="size-4 text-muted-foreground" />
            </button>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={onBack}
        className="mt-6 text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
      >
        Use a different account
      </button>
    </>
  );
}

/**
 * What went wrong, in the words the server used.
 *
 * A refused sign-in and an unreachable API are different problems with different fixes, so they
 * get different messages. Nothing here guesses which credential was wrong — the server does not
 * say, on purpose.
 */
function SignInError({ error }: { error: Error | null }) {
  if (!error) return null;

  const unreachable = error instanceof NetworkError;
  const message =
    error instanceof ApiError || unreachable
      ? error.message
      : "Something went wrong. Nothing was changed.";

  return (
    <div
      role="alert"
      className="mt-6 flex items-start gap-2.5 rounded-md border border-[var(--ub-danger)] bg-danger-soft px-3.5 py-3"
    >
      {unreachable ? (
        <WifiOff aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
      ) : (
        <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
      )}
      <p className="text-sm text-foreground">{message}</p>
    </div>
  );
}

function Field({
  label,
  error,
  htmlFor,
  children,
}: {
  label: string;
  //  Explicitly  rather than just optional:  makes
  //  "may be absent" and "may be undefined" different types, and react-hook-form hands us the
  //  second one.
  error?: string | undefined;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1.5 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function inputClass(invalid: boolean): string {
  return cn(
    "w-full rounded-md border bg-card px-3 py-2 text-sm",
    "transition-colors duration-150 placeholder:text-muted-foreground",
    invalid ? "border-[var(--ub-danger)]" : "border-border",
  );
}
