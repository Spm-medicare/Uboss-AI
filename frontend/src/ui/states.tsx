"use client";

import {
  AlertTriangle,
  Inbox,
  Loader2,
  Lock,
  RefreshCw,
  WifiOff,
} from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { ApiError, NetworkError } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { Button } from "@/ui/button";

/**
 * The five states every route has, whether or not it implements them.
 *
 * PLAN line 605: "Every route defines loading, error, empty, denied and offline/reconnect
 * behavior." A screen that only draws the happy path still *has* the other four — it just shows
 * them as a blank page, a spinner that never stops, or a toast claiming success. These make the
 * other four cost one line each, so there is no reason to skip them.
 *
 * Two rules from the frontend's own README, and they are the ones that get broken quietly:
 *
 * * **Never show a value the backend did not return.** No placeholder counts, no sample rows.
 * * **A failure renders a failure.** Never an empty state — "there is nothing here" and "we could
 *   not find out" look identical to a person and mean opposite things.
 */

function Frame({
  icon,
  tone = "muted",
  title,
  children,
  action,
}: {
  icon: ReactNode;
  tone?: "muted" | "danger" | "warning";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center gap-3 px-6 py-12 text-center"
    >
      <span
        aria-hidden
        className={cn(
          "grid size-10 place-items-center rounded-full",
          tone === "danger" && "bg-danger-soft text-danger",
          tone === "warning" && "bg-approval-soft text-approval",
          tone === "muted" && "bg-muted text-muted-foreground",
        )}
      >
        {icon}
      </span>
      <p className="text-sm font-medium">{title}</p>
      {children ? (
        <p className="max-w-sm text-sm text-muted-foreground">{children}</p>
      ) : null}
      {action}
    </div>
  );
}

/** Something is on its way. Announced politely, so a screen reader is not interrupted. */
export function LoadingState({ label }: { label?: string }) {
  const t = useTranslations("states");
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-2 px-6 py-12 text-sm text-muted-foreground"
    >
      <Loader2 aria-hidden className="size-4 animate-spin" />
      {label ?? t("loading")}
    </div>
  );
}

/**
 * There is genuinely nothing here.
 *
 * **Only after a successful response.** An empty state on a failed request tells a person their
 * data is gone, which is a much worse lie than an error message.
 */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <Frame icon={<Inbox className="size-5" />} title={title} action={action}>
      {description}
    </Frame>
  );
}

/**
 * Something failed, and the person is told what and whether to retry.
 *
 * `retryable` comes from the server's error envelope (PLAN §28) and is never guessed. Offering
 * "try again" on a command that already took effect is how a duplicate is created.
 */
export function ErrorState({
  error,
  onRetry,
}: {
  error: Error;
  onRetry?: () => void;
}) {
  const t = useTranslations("states");
  const offline = error instanceof NetworkError;
  const retryable = offline || (error instanceof ApiError && error.retryable);

  return (
    <Frame
      icon={
        offline ? <WifiOff className="size-5" /> : <AlertTriangle className="size-5" />
      }
      tone="danger"
      title={offline ? t("offlineTitle") : t("errorTitle")}
      action={
        onRetry && retryable ? (
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="size-3.5" />}
            onClick={onRetry}
          >
            {t("retry")}
          </Button>
        ) : undefined
      }
    >
      {error.message}
      {error instanceof ApiError && error.correlationId ? (
        <>
          {" "}
          <span className="font-mono text-xs opacity-70">
            {t("reference", { id: error.correlationId })}
          </span>
        </>
      ) : null}
    </Frame>
  );
}

/**
 * The person is signed in and not allowed.
 *
 * Says nothing about *why*, and nothing about the target. The reason is in the audit trail, where
 * an administrator can read it — a refusal that explains itself confirms the resource exists.
 */
export function DeniedState({ action }: { action?: ReactNode }) {
  const t = useTranslations("states");
  return (
    <Frame
      icon={<Lock className="size-5" />}
      tone="warning"
      title={t("deniedTitle")}
      action={action}
    >
      {t("deniedBody")}
    </Frame>
  );
}

/** The browser has no connection. Distinct from a server error: the fix is different. */
export function OfflineState({ onRetry }: { onRetry?: () => void }) {
  const t = useTranslations("states");
  return (
    <Frame
      icon={<WifiOff className="size-5" />}
      tone="warning"
      title={t("offlineTitle")}
      action={
        onRetry ? (
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="size-3.5" />}
            onClick={onRetry}
          >
            {t("retry")}
          </Button>
        ) : undefined
      }
    >
      {t("offlineBody")}
    </Frame>
  );
}

/**
 * The whole set, resolved from one query's result.
 *
 * The order is the point: **error before empty**. Reversed, a failed request renders "nothing
 * here" and a person concludes their data is gone.
 */
export function QueryStates({
  isPending,
  error,
  isEmpty,
  emptyTitle,
  emptyDescription,
  onRetry,
  children,
}: {
  isPending: boolean;
  error: Error | null;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  onRetry?: () => void;
  children: ReactNode;
}) {
  if (isPending) return <LoadingState />;

  if (error) {
    if (error instanceof ApiError && error.isDenied) return <DeniedState />;
    return <ErrorState error={error} {...(onRetry ? { onRetry } : {})} />;
  }

  if (isEmpty) {
    return (
      <EmptyState
        title={emptyTitle ?? ""}
        {...(emptyDescription ? { description: emptyDescription } : {})}
      />
    );
  }

  return <>{children}</>;
}
