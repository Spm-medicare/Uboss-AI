"use client";

import { useTranslations } from "next-intl";
import { useId, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A label, a control, and — when there is one — the message that belongs to it.
 *
 * The wiring is the point, and it is the part that is skipped when a screen builds its own:
 *
 * * the label is `for` the control, so clicking it focuses the control;
 * * the error and the hint are `aria-describedby` the control, so a screen reader reads them
 *   *with* the field rather than as loose text somewhere on the page;
 * * `aria-invalid` marks the control itself, so assistive technology knows which field is wrong
 *   without inferring it from a red border it cannot see.
 *
 * A required field is marked with a word, not an asterisk — an asterisk means nothing to someone
 * who has not been told what it means.
 */
export function Field({
  label,
  children,
  error,
  hint,
  required = false,
  htmlFor,
  action,
}: {
  label: string;
  /** Receives the resolved ids. The control must spread them or none of the above is true. */
  children: (props: {
    id: string;
    "aria-describedby": string | undefined;
    "aria-invalid": boolean | undefined;
  }) => ReactNode;
  /**
   * A message *key*, not a sentence. Schemas name their messages so a validation string is
   * translated like every other string; `undefined` is explicit because react-hook-form hands
   * back `string | undefined` and `exactOptionalPropertyTypes` treats that as different from
   * "absent".
   */
  error?: string | undefined;
  hint?: string | undefined;
  required?: boolean;
  htmlFor?: string;
  /**
   * A control that belongs to this field but is not part of it — "Forgot password?" beside a
   * password label. On the label's own line so the eye never has to leave the field, and after
   * the label in the DOM so the reading order is still label, control, message.
   */
  action?: ReactNode;
}) {
  const generated = useId();
  const id = htmlFor ?? generated;
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const t = useTranslations("common");
  //  Rooted at the catalogue: the key a schema produced is fully qualified.
  const tRoot = useTranslations();

  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") ||
    undefined;

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="block text-sm font-medium">
          {label}
          {required ? null : (
            <span className="ml-1.5 font-normal text-muted-foreground">
              {t("optional")}
            </span>
          )}
        </label>
        {action}
      </div>

      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
      })}

      {hint ? (
        <p id={hintId} className="mt-1.5 text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}

      {error ? (
        //  `role="alert"` so the message is announced when it appears, not only when the field is
        //  next visited. A person who submitted and heard nothing assumes it worked.
        <p id={errorId} role="alert" className="mt-1.5 text-sm text-danger">
          {tRoot(error)}
        </p>
      ) : null}
    </div>
  );
}

export const controlClass = cn(
  "w-full rounded-md border bg-card px-3 py-2 text-sm",
  "transition-colors duration-150 placeholder:text-muted-foreground",
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ub-focus)]",
  "disabled:cursor-not-allowed disabled:opacity-60",
  //  Driven by `aria-invalid`, so the border and the announcement can never disagree — one
  //  attribute sets both, and there is no way to style a field red without also marking it.
  "border-border aria-invalid:border-danger",
);
