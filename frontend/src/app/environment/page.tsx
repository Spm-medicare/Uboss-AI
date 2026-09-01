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

import { useTranslations } from "next-intl";

import { fetchReadiness } from "@/lib/api/health";
import { NetworkError } from "@/lib/api/errors";
import { applyThemeChoice, useTheme } from "@/lib/theme";
import { Badge, Button, Card } from "@/ui";

/**
 * The environment page.
 *
 * It exists so that "is this thing actually wired up?" has an answer that comes from the running
 * system rather than from a status badge someone typed. Every value on screen is either measured
 * now or labelled as not yet built. Nothing is invented.
 */
export default function EnvironmentPage() {
  const t = useTranslations("environment");
  const tProduct = useTranslations("product");
  const tCommon = useTranslations("common");
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
              <p className="text-sm font-semibold">{tProduct("name")}</p>
              <p className="text-xs text-muted-foreground">{t("eyebrow")}</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto max-w-4xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("title")}
        </h1>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          {t("intro")}
        </p>

        <section className="mt-8" aria-labelledby="api-heading">
          <div className="flex items-center justify-between">
            <h2 id="api-heading" className="text-sm font-semibold">
              {t("apiHeading")}
            </h2>
            <Button
              size="sm"
              onClick={() => void readiness.refetch()}
              busy={readiness.isFetching}
              icon={<RefreshCw className="size-3.5" />}
            >
              {readiness.isFetching ? tCommon("checking") : t("checkAgain")}
            </Button>
          </div>

          <Card className="mt-3 p-5">
            <ReadinessBody
              isPending={readiness.isPending}
              error={readiness.error}
              data={readiness.data}
            />
          </Card>
        </section>

        <section className="mt-10" aria-labelledby="built-heading">
          <h2 id="built-heading" className="text-sm font-semibold">
            {t("builtHeading")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("builtSubtitle")}
          </p>
          <Card as="div" className="mt-3 overflow-hidden">
            <ul className="divide-y divide-border">
            {FOUNDATION_KEYS.map((key) => (
              <li key={key} className="flex items-start gap-3 px-5 py-3.5">
                <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
                <div>
                  <p className="text-sm font-medium">{t(`built.${key}.name`)}</p>
                  <p className="text-sm text-muted-foreground">{t(`built.${key}.detail`)}</p>
                </div>
              </li>
              ))}
            </ul>
          </Card>
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
  const t = useTranslations("environment");

  if (isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 aria-hidden className="size-4 animate-spin" />
        {t("asking")}
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
            {unreachable ? t("unreachableTitle") : t("erroredTitle")}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{error.message}</p>
          {unreachable ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {t("startItWith")}{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                uvicorn uboss.main:app --reload
              </code>{" "}
              {t("orBringUpStack")}{" "}
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
          {ready ? t("ready") : t("degraded")}
        </p>
      </div>

      <dl className="mt-4 space-y-2">
        {data.dependencies.map((dependency) => (
          <div
            key={dependency.name}
            className="flex items-center justify-between gap-4 rounded-md bg-muted/60 px-3 py-2"
          >
            <dt className="text-sm capitalize">{dependency.name}</dt>
            <dd>
              <Badge tone={dependency.ok ? "success" : "danger"}>
                {dependency.ok ? t("answering") : dependency.detail || t("notAnswering")}
              </Badge>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ThemeToggle() {
  const t = useTranslations("a11y");
  // Read from the document rather than from component state: the bootstrap script set the theme
  // before React existed, and another tab or the operating system can change it later.
  const { resolved } = useTheme();
  const isDark = resolved === "dark";

  return (
    <Button
      size="sm"
      onClick={() => applyThemeChoice(isDark ? "light" : "dark")}
      aria-label={isDark ? t("toLight") : t("toDark")}
      icon={isDark ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
    >
      {isDark ? t("light") : t("dark")}
    </Button>
  );
}

/**
 * The keys of the things that are actually finished. The text is in the catalogue.
 *
 * A key is added here only once the thing behind it works end to end — a row on this page is a
 * claim, and this page exists to be believable.
 */
const FOUNDATION_KEYS = [
  "apiSkeleton",
  "tenantBoundary",
  "permissionCeiling",
  "designTokens",
  "files",
  "outboxRelay",
  "tests",
] as const;
