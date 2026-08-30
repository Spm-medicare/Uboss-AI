"use client";

import { AlertTriangle, Check, CloudOff, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Badge } from "@/ui/badge";

/**
 * The Builder chrome, exactly as PLAN §29 specifies it:
 *
 *     Header: breadcrumb, title, status, owner, version, save state
 *     Left: section navigation
 *     Center: form/editor
 *     Right: contextual help, warnings and summary
 *     Sticky footer: Save Draft | Preview Summary | Continue/Analyze/Publish
 *
 * Shared rather than written per Builder, because §6 calls it the *shared* Builder experience and
 * three screens that each drew their own would drift apart within a week — the Job Builder and
 * the Agent Builder use this same frame.
 *
 * The right column collapses below `xl` and the left below `lg`. On a phone the section
 * navigation becomes a scrolling row of pills: a fixed side rail on a narrow screen either eats
 * the form or hides itself, and both are worse than a row that scrolls.
 */

export type SaveState =
  | { kind: "clean" }
  | { kind: "saving" }
  | { kind: "saved"; at: Date }
  | { kind: "offline" }
  | { kind: "failed"; message: string };

export interface BuilderSection {
  id: string;
  label: string;
  /** Shown as a dot when the section has something the person still needs to look at. */
  attention?: boolean;
  /** Filled sections read as done, so a long form shows its own progress honestly. */
  complete?: boolean;
}

export function BuilderLayout({
  eyebrow,
  title,
  status,
  meta,
  saveState,
  sections,
  activeSection,
  onSelectSection,
  aside,
  asideOpen = true,
  footer,
  children,
}: {
  eyebrow: string;
  title: string;
  status: ReactNode;
  /** Owner, version, and anything else that belongs beside the title. */
  meta?: ReactNode;
  saveState: SaveState;
  sections: BuilderSection[];
  activeSection: string;
  onSelectSection: (id: string) => void;
  aside?: ReactNode;
  /** False once somebody has put the guidance panel away. */
  asideOpen?: boolean;
  footer: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("builder");

  return (
    <div className="flex min-h-full flex-col">
      {/*  The header sits above the columns, not inside them, so the title and save state stay
          put while the form scrolls. */}
      <header className="border-b border-border pb-5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {eyebrow}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {status}
          <span className="ml-auto">
            <SaveStateBadge state={saveState} />
          </span>
        </div>
        {meta ? (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {meta}
          </div>
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1 gap-8 pt-6">
        <nav
          aria-label={t("sections")}
          className="hidden w-52 shrink-0 lg:block"
        >
          {/*  Sticky, so the section list is reachable from anywhere in a long form without
              scrolling back up. */}
          <ul className="sticky top-[calc(var(--ub-topbar-height)+1.5rem)] space-y-0.5">
            {sections.map((section, index) => (
              <li key={section.id}>
                <SectionButton
                  section={section}
                  index={index}
                  active={section.id === activeSection}
                  onSelect={() => onSelectSection(section.id)}
                />
              </li>
            ))}
          </ul>
        </nav>

        {/*  Below `lg`, the same list as a scrolling row. */}
        <div className="lg:hidden">
          <ul
            aria-label={t("sections")}
            className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-3"
          >
            {sections.map((section, index) => (
              <li key={section.id} className="shrink-0">
                <SectionButton
                  section={section}
                  index={index}
                  active={section.id === activeSection}
                  onSelect={() => onSelectSection(section.id)}
                  compact
                />
              </li>
            ))}
          </ul>
        </div>

        {/*  §29: "readable form width". Capped, because a form field stretched across a wide
            monitor is a field nobody can scan. */}
        <div className="min-w-0 flex-1 pb-6">
          {/*  **One card, not ten.**
              
              Each section used to be its own bordered card with a gap between them, which is a
              stack of ten cards where the workbook has one sheet. The client asked for the sheet:
              a single frame with section bands inside it, so a form reads as one document rather
              than as a pile of unrelated panels — and so the numbered rail on the left points at
              bands of one thing rather than at ten separate things.

              Wider than a reading column, because the forms are workbook sheets and Form 3's
              table has sixteen columns. 48rem forced a nine-column table to scroll on a monitor
              with room for it. Prose inside a section still sets its own `max-w-prose`. */}
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
            {children}
          </div>
        </div>

        {/*  Closable, because it is guidance rather than form. Somebody who has read it once
            wants the width back, and a panel that cannot be put away is one people learn to
            ignore instead. Reopened from the button that takes its place. */}
        {aside && asideOpen ? (
          <aside className="hidden w-[19rem] shrink-0 xl:block">
            <div className="sticky top-[calc(var(--ub-topbar-height)+1.5rem)] space-y-4">
              {aside}
            </div>
          </aside>
        ) : null}
      </div>

      {/*  §29's sticky footer — reachable from any scroll position, which is the point of a
          form this long.

          Sticky within the column rather than fixed to the viewport: fixed would need to know
          the sidebar's width, and the sidebar collapses. */}
      <div
        className={cn(
          "sticky bottom-0 z-20 -mx-4 border-t border-border px-4 sm:-mx-6 sm:px-6",
          "bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80",
        )}
      >
        <div className="flex flex-wrap items-center gap-2 py-3">{footer}</div>
      </div>
    </div>
  );
}

function SectionButton({
  section,
  index,
  active,
  onSelect,
  compact = false,
}: {
  section: BuilderSection;
  index: number;
  active: boolean;
  onSelect: () => void;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? "step" : undefined}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm",
        "transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        active
          ? "bg-accent font-medium text-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
        compact && "w-auto whitespace-nowrap border border-border",
      )}
    >
      {/*  The number always shows. A tick that *replaced* it made the rail read
          1, ✓, 3, 4, 5, 6, 7, ✓, 9, 10 — so "Current process" stopped being step 2 the moment
          it was filled in, and somebody asking a colleague to "look at step 8" had to count.
          Completion is the colour and the small tick on the corner, both of which are additions
          to the number rather than a replacement for it. */}
      <span aria-hidden className="relative shrink-0">
        <span
          className={cn(
            "grid size-5 place-items-center rounded-full text-[0.6875rem] font-semibold tabular-nums",
            section.complete
              ? "bg-success-soft text-success"
              : active
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground",
          )}
        >
          {index + 1}
        </span>
        {section.complete ? (
          <Check
            className="absolute -right-1 -top-1 size-3 rounded-full bg-success p-px text-white"
            strokeWidth={3.5}
          />
        ) : null}
      </span>
      <span className="min-w-0 flex-1 truncate">{section.label}</span>
      {section.attention ? (
        <span
          aria-hidden
          className="size-1.5 shrink-0 rounded-full bg-approval"
          title="Needs a look"
        />
      ) : null}
    </button>
  );
}

/**
 * Saving / Saved / Offline / Failed — PLAN §6 asks for all four by name.
 *
 * A form that autosaves and says nothing is a form people do not trust, and one that says "Saved"
 * when the request failed is worse than one that says nothing. `failed` carries the server's own
 * message, because "could not save" tells nobody what to do.
 */
export function SaveStateBadge({ state }: { state: SaveState }) {
  const t = useTranslations("builder");

  switch (state.kind) {
    case "saving":
      return (
        <span
          role="status"
          aria-live="polite"
          className="flex items-center gap-1.5 text-xs text-muted-foreground"
        >
          <Loader2 aria-hidden className="size-3.5 animate-spin motion-reduce:animate-none" />
          {t("saving")}
        </span>
      );
    case "saved":
      return (
        <span
          role="status"
          aria-live="polite"
          className="flex items-center gap-1.5 text-xs text-success"
        >
          <Check aria-hidden className="size-3.5" />
          {t("savedAt", {
            time: state.at.toLocaleTimeString(undefined, {
              hour: "numeric",
              minute: "2-digit",
            }),
          })}
        </span>
      );
    case "offline":
      return (
        <Badge tone="approval" icon={<CloudOff className="size-3" />}>
          {t("offline")}
        </Badge>
      );
    case "failed":
      return (
        <Badge tone="danger" icon={<AlertTriangle className="size-3" />}>
          {t("notSaved")}
        </Badge>
      );
    case "clean":
      return null;
  }
}

/** One group of fields, with an anchor the section navigation scrolls to. */
export function BuilderSectionCard({
  id,
  title,
  letter,
  description,
  accent = "primary",
  action,
  flush = false,
  children,
}: {
  id: string;
  title: string;
  /**
   * The workbook's own section letter — Form 4's `A`, `B`, `C`.
   *
   * Present only where the sheet has one. The client refers to these out loud ("put it in section
   * B"), so the letter is part of the name rather than an ornament; the sections §9 adds have no
   * letter on the sheet and get none here, because inventing one would put a label on screen that
   * is not on the form they print.
   */
  letter?: string;
  description?: string;
  /** The stripe down the left edge. Meaning, not decoration — see the call site. */
  accent?: "primary" | "human" | "ai" | "hybrid" | "approval" | "success" | "danger";
  /** A control belonging to the whole section — a toggle, a count. */
  action?: ReactNode;
  /** For a section whose content draws its own edges, like the step table. */
  flush?: boolean;
  children: ReactNode;
}) {
  const stripes: Record<string, string> = {
    primary: "before:bg-primary",
    human: "before:bg-human",
    ai: "before:bg-ai",
    hybrid: "before:bg-hybrid",
    approval: "before:bg-approval",
    success: "before:bg-success",
    danger: "before:bg-danger",
  };

  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className={cn(
        "relative scroll-mt-[calc(var(--ub-topbar-height)+1.5rem)]",
        //  A band inside the sheet, not a card of its own: no border of its own, no rounding, no
        //  gap. The rule above it is what separates one band from the next.
        "border-t border-border first:border-t-0",
        //  A 3px stripe rather than a coloured header: it marks the section at a glance without
        //  tinting the text, which is where contrast goes wrong first.
        "before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:content-['']",
        stripes[accent],
      )}
    >
      <div className="flex items-start justify-between gap-4 bg-muted/40 px-5 py-3 pl-6">
        <div className="min-w-0">
          <h3 id={`${id}-heading`} className="flex items-baseline gap-2 text-sm font-semibold">
            {letter ? (
              <span
                aria-hidden
                className="grid size-5 shrink-0 place-items-center rounded bg-card text-[0.6875rem] font-bold text-muted-foreground ring-1 ring-inset ring-border"
              >
                {letter}
              </span>
            ) : null}
            {title}
          </h3>
          {description ? (
            <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className={cn(flush ? "" : "space-y-4 px-5 py-5 pl-6")}>{children}</div>
    </section>
  );
}
