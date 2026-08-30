"use client";

import { Check, Lock, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/cn";
import { Field } from "@/ui";
import { AuthInput } from "@/ui/auth/auth-input";

/**
 * Choosing a password — used by the reset screen, invitation acceptance and sign-up.
 *
 * **The rules shown here are the server's, and only the ones it actually enforces.**
 * `passwords.check_strength` refuses a password shorter than the minimum or longer than the
 * maximum, and nothing else. So this shows length and a confirmation match, and does not draw a
 * meter or demand a symbol — a client rule stricter than the server's refuses passwords the
 * system would have accepted, and a meter implies a judgement nothing here makes.
 *
 * **Nothing is marked wrong before anything is typed.** Two red crosses under an empty form is
 * the interface telling somebody they have failed at a task they have not started. The list
 * appears on the first keystroke and each line turns from pending to met as it becomes true —
 * so it reads as progress, which is what it is.
 */

//  Mirrors `passwords.MINIMUM_LENGTH`. Duplicated deliberately and marked as such: the server
//  refuses regardless, and this only spares a round trip. If they ever disagree the server wins,
//  which is why the submit button is not gated on this value alone.
export const MINIMUM_LENGTH = 12;

export function PasswordFields({
  password,
  confirmation,
  onPassword,
  onConfirmation,
  disabled = false,
  passwordLabel,
  autoFocus = false,
}: {
  password: string;
  confirmation: string;
  onPassword: (value: string) => void;
  onConfirmation: (value: string) => void;
  disabled?: boolean;
  /** "New password" when replacing one, plain "Password" when choosing a first. */
  passwordLabel?: string;
  autoFocus?: boolean;
}) {
  const t = useTranslations("recovery");

  const started = password.length > 0 || confirmation.length > 0;
  const longEnough = password.length >= MINIMUM_LENGTH;
  const matches = password.length > 0 && password === confirmation;

  return (
    <div className="space-y-4">
      <Field label={passwordLabel ?? t("newPassword")} htmlFor="new-password" required>
        {(field) => (
          <AuthInput
            {...field}
            type="password"
            reveal
            icon={<Lock className="size-4" />}
            autoComplete="new-password"
            autoFocus={autoFocus}
            disabled={disabled}
            value={password}
            onChange={(event) => onPassword(event.target.value)}
          />
        )}
      </Field>

      <Field label={t("confirmPassword")} htmlFor="confirm-password" required>
        {(field) => (
          <AuthInput
            {...field}
            type="password"
            reveal
            icon={<Lock className="size-4" />}
            autoComplete="new-password"
            disabled={disabled}
            value={confirmation}
            onChange={(event) => onConfirmation(event.target.value)}
          />
        )}
      </Field>

      {/*  Two facts, not a score, and only once there is something to judge. `aria-live` so a
          screen reader hears them change rather than having to go looking — and the region
          exists from the start, empty, because one that appears cannot announce its own
          arrival. */}
      <ul aria-live="polite" className={cn("space-y-2 text-sm", started ? "pt-0.5" : "sr-only")}>
        {started ? (
          <>
            <Requirement met={longEnough} label={t("atLeast", { count: MINIMUM_LENGTH })} />
            <Requirement met={matches} label={t("bothMatch")} />
          </>
        ) : null}
      </ul>
    </div>
  );
}

function Requirement({ met, label }: { met: boolean; label: string }) {
  return (
    <li className="flex items-center gap-2">
      <span
        aria-hidden
        className={cn(
          "grid size-4 shrink-0 place-items-center rounded-full transition-colors duration-150 motion-reduce:transition-none",
          met ? "bg-success text-white" : "bg-muted text-muted-foreground",
        )}
      >
        {met ? <Check className="size-2.5" strokeWidth={3} /> : <X className="size-2.5" strokeWidth={3} />}
      </span>
      <span className={met ? "text-foreground" : "text-muted-foreground"}>{label}</span>
    </li>
  );
}

/** Whether the two boxes are in a state worth submitting. The server checks again regardless. */
export function isSubmittable(password: string, confirmation: string): boolean {
  return password.length >= MINIMUM_LENGTH && password === confirmation;
}
