import { cva, type VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A small piece of state — a status, a work mode, a version.
 *
 * **Colour is never the only signal.** `ui/README.md` forbids colour-only status, and the reason
 * is ordinary rather than theoretical: around one in twelve men cannot separate the red badge
 * from the green one. Every badge carries a word; the colour reinforces it and never replaces it.
 *
 * The tones are the vocabulary of PLAN §29 — human, AI and hybrid work modes, plus the three
 * outcomes. There is no `custom`. A screen that needs a colour this does not have needs a
 * decision about what that colour *means*, not a hex value.
 */
const badge = cva(
  [
    "inline-flex items-center gap-1 whitespace-nowrap rounded-full",
    "px-2 py-0.5 text-xs font-medium",
  ],
  {
    variants: {
      tone: {
        neutral: "bg-muted text-muted-foreground",
        human: "bg-human-soft text-human",
        ai: "bg-ai-soft text-ai",
        hybrid: "bg-hybrid-soft text-hybrid",
        approval: "bg-approval-soft text-approval",
        success: "bg-success-soft text-success",
        danger: "bg-danger-soft text-danger",
      },
      outline: { true: "border border-border bg-transparent", false: "" },
    },
    defaultVariants: { tone: "neutral", outline: false },
  },
);

export interface BadgeProps extends VariantProps<typeof badge> {
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function Badge({ tone, outline, icon, children, className }: BadgeProps) {
  return (
    <span className={cn(badge({ tone, outline }), className)}>
      {icon ? (
        <span aria-hidden className="inline-flex">
          {icon}
        </span>
      ) : null}
      {children}
    </span>
  );
}
