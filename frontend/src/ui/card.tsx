import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A bounded surface.
 *
 * Exists so a page never writes `rounded-lg border border-border bg-card` itself — which sounds
 * trivial until three screens each pick a slightly different radius and the product starts to
 * look assembled rather than designed.
 */
export function Card({
  children,
  className,
  as: Component = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article" | "li";
}) {
  return (
    <Component
      className={cn("rounded-lg border border-border bg-card", className)}
    >
      {children}
    </Component>
  );
}

/** A card's heading strip, separated from its body. */
export function CardHeader({
  title,
  description,
  action,
  id,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
      <div className="min-w-0">
        <h2 id={id} className="text-sm font-semibold">
          {title}
        </h2>
        {description ? (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function CardBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("px-5 py-4", className)}>{children}</div>;
}

/**
 * Label-and-value pairs — a profile, a version's provenance, an audit entry.
 *
 * A real `<dl>` rather than a two-column grid of `<div>`s, because the association between a
 * label and its value is the whole content here, and a grid throws it away for anyone not
 * looking at the screen.
 */
export function DescriptionList({ children }: { children: ReactNode }) {
  return <dl className="divide-y divide-border">{children}</dl>;
}

export function DescriptionRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1 px-5 py-3.5 sm:flex-row sm:items-baseline sm:gap-6">
      <dt className="w-44 shrink-0 text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  );
}
