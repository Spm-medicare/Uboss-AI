"use client";

import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Spinner } from "@/ui/spinner";

/**
 * The only button in the product.
 *
 * `frontend/src/ui/README.md` forbids new button styling inside feature folders, and this is why
 * that rule can hold: every variant a screen could need is here, so there is never a reason to
 * write one. A page that declares its own `bg-blue-600` is a page that will not follow the next
 * palette change, and nobody will notice until a screenshot looks wrong.
 *
 * **Colours come from tokens, never literals** — see `styles/tokens.css`. `bg-primary` means the
 * same thing in light and dark; `bg-blue-600` means blue in both, including where blue is
 * unreadable.
 *
 * **A busy button says so and stops accepting clicks.** Not because a second click would look
 * untidy, but because a second click is a second command — and PLAN §28's idempotency keys exist
 * precisely because that happens.
 */
const button = cva(
  [
    "inline-flex items-center justify-center gap-1.5 whitespace-nowrap",
    "rounded-md font-medium",
    "transition-colors duration-150",
    //  Focus is never removed. A keyboard user who cannot see where they are cannot use the
    //  product at all — this is the difference between usable and unusable, not a nicety.
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
    "disabled:pointer-events-none disabled:opacity-60",
  ],
  {
    variants: {
      variant: {
        //  One clear primary action per screen — PLAN §29. If two buttons on a screen are
        //  primary, neither is.
        primary: "bg-primary text-primary-foreground hover:bg-[var(--ub-brand-hover)]",
        secondary: "border border-border bg-card hover:bg-accent",
        ghost: "hover:bg-accent",
        //  Destructive is its own variant so that "delete" never has to be hand-coloured, and so
        //  the one review question — is this really destructive? — is asked at the call site.
        danger: "bg-danger text-danger-foreground hover:opacity-90",
      },
      size: {
        sm: "h-8 px-2.5 text-xs",
        md: "h-9 px-3.5 text-sm",
        lg: "h-11 px-5 text-sm",
      },
      block: { true: "w-full", false: "" },
    },
    defaultVariants: { variant: "secondary", size: "md", block: false },
  },
);

export interface ButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "color">,
    VariantProps<typeof button> {
  /** Shows a spinner and refuses clicks. The label stays, so the button does not change width. */
  busy?: boolean;
  /** Rendered before the label, and hidden from assistive technology — the label already says it. */
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, block, busy = false, icon, children, disabled, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      //  Defaulted, because a button inside a form with no type is a submit button, and that has
      //  surprised somebody on every project that did not do this.
      type={type ?? "button"}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cn(button({ variant, size, block }), className)}
      {...rest}
    >
      {busy ? (
        <Spinner />
      ) : icon ? (
        <span aria-hidden className="inline-flex">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
});
