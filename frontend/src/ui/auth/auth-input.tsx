"use client";

import { Eye, EyeOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Input } from "@/ui";

/**
 * A text box with a mark in front of it, and — for passwords — a way to see what you typed.
 *
 * The leading glyph is not decoration. On a signed-out screen the two fields look identical at a
 * glance, and an envelope beside one of them is the fastest way to tell them apart without
 * reading. It is `aria-hidden`: the label already says what the field is, and a screen reader
 * announcing "envelope, work email" is noise.
 *
 * **The reveal is a button, not a hover state.** Somebody typing a long passphrase on a phone
 * needs to see it, and a hover-only control does not exist on the device where that matters
 * most. `aria-pressed` carries the state, so it is a toggle rather than two mystery icons.
 */
export function AuthInput({
  icon,
  reveal = false,
  className,
  type = "text",
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & {
  icon?: ReactNode;
  /** Adds the show/hide toggle. Only meaningful on a password field. */
  reveal?: boolean;
}) {
  const t = useTranslations("recovery");
  const [visible, setVisible] = useState(false);
  const describedBy = useId();

  return (
    <div className="relative">
      {icon ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 grid w-10 place-items-center text-muted-foreground"
        >
          {icon}
        </span>
      ) : null}

      <Input
        {...rest}
        type={reveal && visible ? "text" : type}
        className={cn(
          "h-11",
          icon ? "pl-10" : undefined,
          reveal ? "pr-11" : undefined,
          className,
        )}
      />

      {reveal ? (
        <button
          type="button"
          onClick={() => setVisible(!visible)}
          aria-pressed={visible}
          aria-controls={describedBy}
          aria-label={visible ? t("hidePassword") : t("showPassword")}
          //  Not in the tab order before the field it belongs to: `tabIndex` is left alone, and
          //  the button follows the input in the DOM, so the order is already right.
          className={cn(
            "absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-md text-muted-foreground",
            "transition-colors duration-150 hover:text-foreground motion-reduce:transition-none",
            "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
          )}
        >
          {visible ? (
            <EyeOff aria-hidden className="size-4" />
          ) : (
            <Eye aria-hidden className="size-4" />
          )}
        </button>
      ) : null}
    </div>
  );
}
