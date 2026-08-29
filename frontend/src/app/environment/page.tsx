"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Moon,
  RefreshCw,
  Sun,
  WifiOff,
} from "lucide-react";

import { fetchReadiness } from "@/lib/api/health";
import { NetworkError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { applyThemeChoice, useTheme } from "@/lib/theme";

/**
 * The environment page.
 *
 * It exists so that "is this thing actually wired up?" has an answer that comes from the running
 * system rather than from a status badge someone typed. Every value on screen is either measured
 * now or labelled as not yet built. Nothing is invented.
 */
export default function EnvironmentPage() {
  const readiness = useQuery({
    queryKey: ["readiness"],
    queryFn: ({ signal }) => fetchReadiness(signal),
    refetchInterval: 15_000,
    retry: false,
  });

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-4xl items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <span className="grid size-8 place-items-center rounded-md bg-primary text-sm font-semibold text-primary-foreground">
              U
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold">UBOSS</p>
              <p className="text-xs text-muted-foreground">Environment</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main id="main" className="mx-auto max-w-4xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">
          Development environment
        </h1>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          The product is being built in the order set out in the plan. This page reports what is
          running right now; it does not report anything that has not been measured.
        </p>

        <section className="mt-8" aria-labelledby="api-heading">
          <div className="flex items-center justify-between">
            <h2 id="api-heading" className="text-sm font-semibold">
              API connection
            </h2>
            <button
              type="button"
              onClick={() => void readiness.refetch()}
              disabled={readiness.isFetching}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5",
                "text-xs font-medium transition-colors duration-150",
                "hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60",
              )}
            >
              <RefreshCw
                aria-hidden
                className={cn("size-3.5", readiness.isFetching && "animate-spin")}
              />
              {readiness.isFetching ? "Checking" : "Check again"}
            </button>
          </div>

          <div className="mt-3 rounded-lg border border-border bg-card p-5">
            <ReadinessBody
              isPending={readiness.isPending}
              error={readiness.error}
              data={readiness.data}
            />
          </div>
        </section>

        <section className="mt-10" aria-labelledby="built-heading">
          <h2 id="built-heading" className="text-sm font-semibold">
            What is wired up
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            A row appears here only once the thing behind it works end to end.
          </p>
          <ul className="mt-3 divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
            {FOUNDATIONS.map((item) => (
              <li key={item.name} className="flex items-start gap-3 px-5 py-3.5">
                <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
                <div>
                  <p className="text-sm font-medium">{item.name}</p>
                  <p className="text-sm text-muted-foreground">{item.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}

function ReadinessBody({
  isPending,
  error,
  data,
}: {
  isPending: boolean;
  error: Error | null;
  data: Awaited<ReturnType<typeof fetchReadiness>> | undefined;
}) {
  if (isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 aria-hidden className="size-4 animate-spin" />
        Asking the API whether it can serve traffic…
      </p>
    );
  }

  //  A failed request renders a failure. It never falls back to sample data, and it never
  //  renders an empty state — an empty state would say "nothing is wrong, there is just no
  //  data", which is the opposite of the truth here.
  if (error) {
    const unreachable = error instanceof NetworkError;
    return (
      <div className="flex items-start gap-3">
        {unreachable ? (
          <WifiOff aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
        ) : (
          <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
        )}
        <div>
          <p className="text-sm font-medium text-danger">
            {unreachable ? "The API could not be reached" : "The API answered with an error"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{error.message}</p>
          {unreachable ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Start it with{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                uvicorn uboss.main:app --reload
              </code>{" "}
              from the <span className="font-medium">backend</span> folder, or bring up the whole
              stack with{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                docker compose -f infra/compose.yaml up
              </code>
              .
            </p>
          ) : null}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const ready = data.status === "ready";

  return (
    <div>
      <div className="flex items-center gap-2">
        {ready ? (
          <CheckCircle2 aria-hidden className="size-4 text-success" />
        ) : (
          <AlertTriangle aria-hidden className="size-4 text-approval" />
        )}
        {/* Icon and words together, never colour alone — PLAN section 29. */}
        <p className="text-sm font-medium">
          {ready ? "Ready to serve traffic" : "Running, but not ready"}
        </p>
      </div>

      <dl className="mt-4 space-y-2">
        {data.dependencies.map((dependency) => (
          <div
            key={dependency.name}
            className="flex items-center justify-between gap-4 rounded-md bg-muted/60 px-3 py-2"
          >
            <dt className="text-sm capitalize">{dependency.name}</dt>
            <dd
              className={cn(
                "text-sm font-medium",
                dependency.ok ? "text-success" : "text-danger",
              )}
            >
              {dependency.ok ? "Answering" : dependency.detail || "Not answering"}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ThemeToggle() {
  // Read from the document rather than from component state: the bootstrap script set the theme
  // before React existed, and another tab or the operating system can change it later.
  const { resolved } = useTheme();
  const isDark = resolved === "dark";

  return (
    <button
      type="button"
      onClick={() => applyThemeChoice(isDark ? "light" : "dark")}
      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium transition-colors duration-150 hover:bg-accent"
    >
      {isDark ? (
        <Sun aria-hidden className="size-3.5" />
      ) : (
        <Moon aria-hidden className="size-3.5" />
      )}
      {isDark ? "Light" : "Dark"}
    </button>
  );
}

/** Only things that are actually finished appear here. */
const FOUNDATIONS: { name: string; detail: string }[] = [
  {
    name: "API skeleton",
    detail:
      "FastAPI with the shared error envelope, correlation ids, security headers and a real readiness probe.",
  },
  {
    name: "Tenant boundary",
    detail:
      "Sessions bind the caller's tenant to the transaction, so row-level security is in force for every statement.",
  },
  {
    name: "Permission ceiling",
    detail:
      "Company → department → resource → action, resolved by intersection so a lower scope can never widen a higher one.",
  },
  {
    name: "Design tokens",
    detail:
      "Semantic colour, spacing, radius and motion tokens in light and dark, with an explicit choice overriding the operating system.",
  },
];
