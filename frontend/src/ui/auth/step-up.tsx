"use client";

import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { stepUpWithPassword } from "@/lib/api/auth";
import { ApiError, NetworkError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { Alert, Button, Field } from "@/ui";
import { AuthInput } from "@/ui/auth/auth-input";

/**
 * Confirming a password before a high-risk action.
 *
 * PLAN §14 marks some verbs high-risk — `administer` among them — and the guard refuses them
 * unless the session has proved a password recently. The refusal is correct and its message is
 * clear: *"Confirm your password to continue."*
 *
 * **There was nowhere to do it.** `stepUpWithPassword` existed and nothing called it, so the
 * whole of Hierarchy editing was a dead end: a person with every permission clicked Create, was
 * told to confirm their password, and was shown no password box anywhere in the product. A
 * screen that states a requirement and offers no way to satisfy it is the worst version of
 * "a control that does not do what it says" — the control is honest and the product is still
 * unusable.
 *
 * ## How it is wired
 *
 * `useStepUp()` returns a wrapper. A caller runs its request through it, and if — and only if —
 * the server answers `step_up_required`, this opens the prompt, waits for the password, and
 * **runs the request once more**. The person clicks once.
 *
 *     const withStepUp = useStepUp();
 *     mutationFn: () => withStepUp(() => createUnit(body))
 *
 * The retry is safe to make automatically because every mutating call carries an idempotency key
 * derived from the operation rather than generated per call — so the second attempt is the same
 * request, not a second one. That property is what makes this a wrapper rather than a message
 * asking somebody to try again themselves.
 *
 * **Exactly one retry.** If the second attempt also comes back `step_up_required`, the error is
 * raised. A loop here would sit between somebody and their work asking for a password for ever.
 */

interface StepUpRequest {
  resolve: () => void;
  reject: (reason: Error) => void;
}

const StepUpContext = createContext<(() => Promise<void>) | null>(null);

/** True when the server refused *only* because the session needs a fresh password proof. */
function needsStepUp(error: unknown): boolean {
  return error instanceof ApiError && error.code === "step_up_required";
}

export function StepUpProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<StepUpRequest | null>(null);
  //  Held in a ref as well, so `close` can settle a request without depending on the state that
  //  is about to be cleared.
  const current = useRef<StepUpRequest | null>(null);

  const require = useCallback(() => {
    return new Promise<void>((resolve, reject) => {
      const request: StepUpRequest = { resolve, reject };
      current.current = request;
      setPending(request);
    });
  }, []);

  const settle = useCallback((outcome: "confirmed" | "cancelled") => {
    const request = current.current;
    current.current = null;
    setPending(null);
    if (!request) return;
    if (outcome === "confirmed") request.resolve();
    //  Cancelling rejects rather than resolving. Resolving would run the original request again,
    //  it would be refused again, and the person would see the refusal they just declined to
    //  clear — as though cancelling had done something.
    else request.reject(new StepUpCancelled());
  }, []);

  return (
    <StepUpContext.Provider value={require}>
      {children}
      {pending ? (
        <StepUpPrompt onConfirmed={() => settle("confirmed")} onCancel={() => settle("cancelled")} />
      ) : null}
    </StepUpContext.Provider>
  );
}

/** The person closed the prompt. Not a failure — nothing was attempted and nothing changed. */
export class StepUpCancelled extends Error {
  constructor() {
    super("step_up_cancelled");
    this.name = "StepUpCancelled";
  }
}

/**
 * Run a request, and if it needs a password proof, collect one and run it again.
 *
 * Returns the request's own result, so a caller uses it exactly where it already had the call.
 */
export function useStepUp(): <T>(run: () => Promise<T>) => Promise<T> {
  const require = useContext(StepUpContext);

  return useCallback(
    async <T,>(run: () => Promise<T>): Promise<T> => {
      try {
        return await run();
      } catch (error) {
        //  Without a provider there is nowhere to ask, so the refusal is passed through
        //  unchanged rather than swallowed — a screen outside the workspace shell should show
        //  the server's message, not fail silently.
        if (!needsStepUp(error) || !require) throw error;
        await require();
        return await run();
      }
    },
    [require],
  );
}

/**
 * The prompt itself.
 *
 * A password box and nothing else. It does not say which action is waiting: this is reached from
 * several places, and a sentence naming the wrong one is worse than a sentence naming none.
 */
function StepUpPrompt({
  onConfirmed,
  onCancel,
}: {
  onConfirmed: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("stepUp");
  const tCommon = useTranslations("common");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await stepUpWithPassword(password);
      //  Cleared before the caller's request runs again, so a wrong password on a later prompt
      //  cannot be submitted from a stale box.
      setPassword("");
      onConfirmed();
    } catch (cause) {
      setError(cause as Error);
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="step-up-title"
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 backdrop-blur-[2px]"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !busy) onCancel();
      }}
    >
      <div
        className={cn(
          "w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-dialog",
        )}
      >
        <div className="flex gap-3.5">
          <span
            aria-hidden
            className="grid size-10 shrink-0 place-items-center rounded-lg bg-approval-soft text-approval"
          >
            <ShieldAlert className="size-5" />
          </span>
          <div className="min-w-0">
            <h2 id="step-up-title" className="text-base font-semibold">
              {t("title")}
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t("body")}</p>
          </div>
        </div>

        <form
          className="mt-5 space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!password || busy) return;
            void confirm();
          }}
        >
          {error ? (
            <Alert tone={error instanceof NetworkError ? "offline" : "danger"}>
              {error instanceof ApiError ? error.message : t("failed")}
            </Alert>
          ) : null}

          <Field label={t("password")} htmlFor="step-up-password" required>
            {(field) => (
              <AuthInput
                {...field}
                type="password"
                reveal
                autoComplete="current-password"
                autoFocus
                disabled={busy}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            )}
          </Field>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>
              {tCommon("cancel")}
            </Button>
            <Button type="submit" variant="primary" busy={busy} disabled={!password}>
              {busy ? t("confirming") : t("confirm")}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
