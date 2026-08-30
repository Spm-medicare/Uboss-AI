"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BadgeCheck,
  FileCheck2,
  LockKeyhole,
  ScrollText,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ReactNode } from "react";

import { fetchSignInMethods } from "@/lib/api/sign-in-methods";
import { cn } from "@/lib/cn";
import { Alert, Button, Spinner } from "@/ui";
import { Monogram, Wordmark } from "@/ui/brand/mark";

/**
 * The frame every signed-out screen sits in — two panels, as the previous build had it.
 *
 * **Left: what this product is.** A deep navy panel carrying the mark, the promise, and three
 * things the system actually enforces. It is the only piece of marketing in the whole
 * application, and it earns its place: somebody typing a password into an unfamiliar tool is
 * deciding whether to trust it, and a bare form answers none of that.
 *
 * **Right: one decision, on the page itself.** No card. A bordered card floating on a background
 * is the shape of a dialog — something that interrupted you — and this page interrupted nobody.
 * The panel edge already divides the screen, so a second frame six inches from it is a box
 * inside a box.
 *
 * Below `lg` the panels stack and the left one collapses to a header strip carrying the mark. A
 * full-height brand panel on a phone would push the form below the fold, which is the one thing a
 * sign-in screen cannot do — and the strip is the *only* lockup there, because the version that
 * also drew one above the form showed the logo twice on every phone.
 *
 * ## The claims on the left are only ones the code keeps
 *
 * "Mandatory human approval", "approved versions only" and "append-only audit trail" are
 * enforced by the approvals module, the immutable `*_versions` tables and the `refuse_change()`
 * triggers respectively. A certification badge or an uptime figure would not be — so there is
 * none, and this file is where that rule is easiest to break.
 */
export function AuthShell({
  title,
  subtitle,
  eyebrow,
  children,
  back,
  tabs,
}: {
  title: string;
  subtitle?: string;
  /** The small uppercase line above the title. Names the room before naming the task. */
  eyebrow?: string;
  children: ReactNode;
  /** A quiet way back — every screen but sign-in has somewhere to return to. */
  back?: { href: string; label: string };
  /** Sign in / Create account. Absent on the recovery screens, which are one path only. */
  tabs?: ReactNode;
}) {
  const t = useTranslations("signIn");
  const tProduct = useTranslations("product");

  return (
    <div className="min-h-dvh bg-background lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      {/*  ── Left: the brand panel ─────────────────────────────────────────── */}
      <aside
        aria-label={tProduct("name")}
        className={cn(
          "relative isolate flex flex-col overflow-hidden px-6 py-6 text-white",
          "bg-[linear-gradient(160deg,var(--ub-auth-panel-from),var(--ub-auth-panel-to))]",
          "lg:sticky lg:top-0 lg:h-dvh lg:px-12 lg:py-11",
        )}
      >
        <PanelRings />

        {/*  ── the lockup ── */}
        <div className="relative flex items-center gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/10 ring-1 ring-inset ring-white/15 backdrop-blur-sm">
            <Monogram className="h-5 text-white" />
          </span>
          <Wordmark className="text-xl" />
        </div>

        {/*  Everything from here down is the pitch, and a phone does not have room for it. The
            mark above stays, so the strip still says whose sign-in screen this is. */}
        <div className="relative mt-14 hidden lg:block">
          <p className="inline-flex items-center gap-2 rounded-full bg-white/[0.07] py-1.5 pl-3 pr-4 text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-sky-200 ring-1 ring-inset ring-white/15">
            <span aria-hidden className="size-1.5 rounded-full bg-sky-300" />
            {t("panelBadge")}
          </p>

          <h2 className="mt-7 max-w-[17ch] text-balance text-4xl font-bold leading-[1.08] tracking-tight xl:text-[2.75rem]">
            {t("panelHeadline")}
          </h2>
          <p className="mt-5 max-w-md text-[0.9375rem] leading-relaxed text-white/70">
            {t("panelBody")}
          </p>

          <ul className="mt-10 space-y-3">
            {(
              [
                ["governed", UserCheck],
                ["approved", FileCheck2],
                ["audited", ScrollText],
              ] as const
            ).map(([key, Icon]) => (
              <li
                key={key}
                className="flex gap-3.5 rounded-xl bg-white/[0.05] p-4 ring-1 ring-inset ring-white/10"
              >
                <Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-sky-300" />
                <span>
                  <span className="block text-[0.9375rem] font-semibold leading-snug">
                    {t(`panel.${key}.title`)}
                  </span>
                  <span className="mt-1 block text-sm leading-relaxed text-white/65">
                    {t(`panel.${key}.body`)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/*  ── the footer strip ── */}
        <div className="relative mt-auto hidden pt-10 lg:block">
          <ul className="flex flex-wrap items-center gap-x-7 gap-y-2 border-t border-white/10 pt-5 text-xs text-white/55">
            {(
              [
                ["isolation", ShieldCheck],
                ["governed", BadgeCheck],
                ["audited", LockKeyhole],
              ] as const
            ).map(([key, Icon]) => (
              <li key={key} className="flex items-center gap-2">
                <Icon aria-hidden className="size-3.5 text-sky-300/70" />
                {t(`panelFooter.${key}`)}
              </li>
            ))}
          </ul>
        </div>
      </aside>

      {/*  ── Right: the form ──────────────────────────────────────────────── */}
      <main id="main" className="grid place-items-center px-6 py-10 lg:px-10 lg:py-12">
        <div className="w-full max-w-[27rem]">
          {back ? (
            <Link
              href={back.href}
              className={cn(
                "mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground",
                "transition-colors duration-150 hover:text-foreground motion-reduce:transition-none",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              )}
            >
              <ArrowLeft aria-hidden className="size-3.5" />
              {back.label}
            </Link>
          ) : null}

          {tabs ? <div className="mb-8">{tabs}</div> : null}

          {eyebrow ? (
            <p className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="mt-2 text-[1.75rem] font-bold leading-tight tracking-tight">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
          ) : null}

          <div className="mt-7">{children}</div>

          <p className="mt-7 flex items-start justify-center gap-2 text-center text-xs leading-relaxed text-muted-foreground">
            <LockKeyhole aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            <span>{t("finePrint")}</span>
          </p>
        </div>
      </main>
    </div>
  );
}

/**
 * The concentric rings behind the panel.
 *
 * Drawn as three borders rather than a background image so they scale with the panel and cost
 * nothing to load. Anchored off the right edge and clipped, which is what makes them read as
 * part of a much larger shape rather than as three circles somebody placed.
 */
function PanelRings() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      {/*  One soft light from the top-left, so the mark sits in the brightest part of the panel. */}
      <div className="absolute inset-0 bg-[radial-gradient(40rem_30rem_at_10%_-5%,rgb(56_130_246/0.28),transparent_70%)]" />
      <div className="absolute -right-[18%] top-1/2 aspect-square w-[46rem] -translate-y-1/2 rounded-full border border-white/[0.07]" />
      <div className="absolute -right-[10%] top-1/2 aspect-square w-[32rem] -translate-y-1/2 rounded-full border border-white/[0.06]" />
      <div className="absolute -right-[4%] top-1/2 aspect-square w-[20rem] -translate-y-1/2 rounded-full border border-white/[0.05]" />
    </div>
  );
}

/**
 * The two tabs, as a segmented control.
 *
 * Real tabs with `role="tab"` and `aria-selected`, not two links styled to look like tabs: they
 * switch a view on the same page, and a screen reader should be told that rather than left to
 * infer it from a highlight.
 *
 * The selected tab is a raised white pill on a sunken track — the shape reads as "this one of
 * two", which an underline does not do as quickly at the top of a page.
 */
export function AuthTabs({
  value,
  onChange,
}: {
  value: "signin" | "register";
  onChange: (next: "signin" | "register") => void;
}) {
  const t = useTranslations("signIn");

  return (
    <div
      role="tablist"
      aria-label={t("tabsLabel")}
      className="grid grid-cols-2 gap-1 rounded-xl border border-border bg-muted p-1"
    >
      {(["signin", "register"] as const).map((option) => (
        <button
          key={option}
          type="button"
          role="tab"
          aria-selected={value === option}
          onClick={() => onChange(option)}
          className={cn(
            "rounded-lg px-4 py-2.5 text-sm font-semibold",
            "transition-colors duration-150 motion-reduce:transition-none",
            "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
            value === option
              ? "bg-card text-primary shadow-sm ring-1 ring-inset ring-border"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t(`tab.${option}`)}
        </button>
      ))}
    </div>
  );
}

/**
 * Google, Microsoft and Apple — all three, always, with the ones this deployment cannot complete
 * **disabled and labelled**.
 *
 * `GET /auth/providers` reports which have credentials. An earlier version hid the rest, which
 * was the wrong reading of the rule: an absent button says the product does not support that
 * provider, which is false. A disabled one with "not configured" on it says what is actually
 * true, and tells whoever is setting the system up exactly what is missing — while still never
 * offering a control that would fail on click.
 *
 * Three-across, as the previous build had them.
 */
export function ProviderButtons({
  onStart,
  busyProvider,
  error,
  purpose = "signin",
}: {
  onStart: (provider: string) => void;
  busyProvider: string | null;
  error?: Error | null;
  purpose?: "signin" | "register";
}) {
  const t = useTranslations("signIn");
  const methods = useQuery({
    queryKey: ["sign-in-methods"],
    queryFn: ({ signal }) => fetchSignInMethods(signal),
    staleTime: 5 * 60 * 1000,
  });

  if (methods.isPending) {
    return (
      <div className="flex justify-center py-3">
        <Spinner />
      </div>
    );
  }

  const providers = methods.data?.oauthProviders ?? [];
  if (providers.length === 0) return null;
  const anyConfigured = providers.some((provider) => provider.configured);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span aria-hidden className="h-px flex-1 bg-border" />
        <span className="whitespace-nowrap text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {purpose === "register" ? t("orRegisterWith") : t("orSignInWith")}
        </span>
        <span aria-hidden className="h-px flex-1 bg-border" />
      </div>

      {error ? <Alert tone="danger">{error.message}</Alert> : null}

      <div
        className={cn("grid gap-2.5", providers.length === 3 ? "grid-cols-3" : "grid-cols-1")}
      >
        {providers.map(({ name, configured }) => (
          <Button
            key={name}
            variant="secondary"
            block
            disabled={!configured}
            busy={busyProvider === name}
            icon={<ProviderGlyph provider={name} />}
            onClick={() => onStart(name)}
            //  The provider's own name is the label. "Continue with Google" in a three-across
            //  grid wraps to two lines on every screen narrower than a laptop. The title says
            //  which it is either way, and why it is disabled when it is.
            title={
              configured
                ? t("continueWith", { provider: t(`provider.${name}`) })
                : t("providerUnavailable", { provider: t(`provider.${name}`) })
            }
            className="h-11 border border-border bg-card font-medium hover:bg-accent"
          >
            {t(`provider.${name}`)}
          </Button>
        ))}
      </div>

      {/*  Said once under the row rather than three times inside it. A person who cannot use any
          of them needs to know it is the deployment's doing, not theirs. */}
      {anyConfigured ? null : (
        <p className="text-center text-xs text-muted-foreground">
          {t("noProvidersConfigured")}
        </p>
      )}
    </div>
  );
}

/**
 * Each provider's mark, drawn rather than fetched.
 *
 * Google's four colours and Microsoft's four squares are fixed by their brand rules and do not
 * follow the theme. Apple's is monochrome and takes `currentColor`, which is what their
 * guidelines ask for.
 */
function ProviderGlyph({ provider }: { provider: string }) {
  if (provider === "google") {
    return (
      <svg viewBox="0 0 48 48" aria-hidden className="size-[1.05rem]">
        <path
          fill="#FFC107"
          d="M43.611 20.083H42V20H24v8h11.303C33.973 32.443 29.418 35 24 35c-6.075 0-11-4.925-11-11s4.925-11 11-11c2.804 0 5.35 1.06 7.29 2.79l5.66-5.66C33.53 7.24 28.99 5 24 5 12.954 5 4 13.954 4 25s8.954 20 20 20 20-8.954 20-20c0-1.341-.138-2.65-.389-3.917z"
        />
        <path
          fill="#FF3D00"
          d="M6.306 14.691l6.571 4.819C14.655 16.108 19.001 13 24 13c2.804 0 5.35 1.06 7.29 2.79l5.66-5.66C33.53 7.24 28.99 5 24 5c-7.682 0-14.344 4.337-17.694 10.691z"
        />
        <path
          fill="#4CAF50"
          d="M24 45c4.896 0 9.359-1.875 12.728-4.939l-5.876-4.97A11.94 11.94 0 0 1 24 37c-5.392 0-9.943-3.437-11.29-8.197l-6.522 5.025C9.505 40.556 16.227 45 24 45z"
        />
        <path
          fill="#1976D2"
          d="M43.611 20.083H42V20H24v8h11.303a11.974 11.974 0 0 1-4.073 5.56l.003-.002 5.875 4.971C36.889 39.213 44 34 44 25c0-1.341-.138-2.65-.389-3.917z"
        />
      </svg>
    );
  }
  if (provider === "microsoft") {
    return (
      <svg viewBox="0 0 21 21" aria-hidden className="size-[1.05rem]">
        <rect x="1" y="1" width="9" height="9" fill="#F25022" />
        <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
        <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
        <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 170 170" aria-hidden className="size-[1.05rem]" fill="currentColor">
      <path d="M150.37 130.25c-2.45 5.66-5.35 10.87-8.71 15.66-4.58 6.53-8.33 11.05-11.22 13.56-4.48 4.12-9.28 6.23-14.42 6.35-3.69 0-8.14-1.05-13.32-3.18-5.19-2.12-9.97-3.17-14.34-3.17-4.58 0-9.49 1.05-14.75 3.17-5.26 2.13-9.5 3.24-12.74 3.35-4.35.13-9.16-1.9-14.42-6.08-3.69-3.04-7.69-7.86-12-14.46-6.1-9.33-10.88-19.82-14.35-31.49-3.48-11.66-5.22-22.84-5.22-33.54 0-14.8 3.73-26.68 11.19-35.63 7.46-8.95 16.71-13.48 27.75-13.59 4.89 0 10.14 1.25 15.75 3.74 5.61 2.49 9.38 3.79 11.31 3.9 1.41-.22 5.38-1.57 11.91-4.05 6.53-2.49 12.01-3.63 16.44-3.43 12.51.65 22.38 5.25 29.6 13.8-10.88 6.53-16.21 15.56-16 27.1.22 9.14 3.76 16.82 10.63 23.03 6.86 6.21 14.94 9.77 24.23 10.69-2.17 6.75-4.99 13.91-8.45 21.48zm-29.21-114.59c.11 2.94-.48 5.92-1.78 8.95-1.3 3.03-3.19 5.8-5.67 8.3-2.72 2.61-5.74 4.54-9.06 5.79-3.32 1.25-6.57 1.83-9.75 1.74-.11-2.94.49-5.88 1.8-8.82 1.31-2.94 3.22-5.69 5.73-8.24 2.61-2.61 5.61-4.56 9-5.85 3.39-1.29 6.63-1.91 9.73-1.87z" />
    </svg>
  );
}
