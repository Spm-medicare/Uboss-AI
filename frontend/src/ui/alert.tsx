import { AlertTriangle, CheckCircle2, Info, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A message about the thing the person is looking at, in place.
 *
 * Not a toast. A toast disappears, which is right for "saved" and wrong for anything a person has
 * to act on — an error that vanished while they were reading it is an error they will meet again.
 *
 * `role="alert"` on the failing tones, so the message is announced the moment it appears rather
 * than waiting to be found.
 */
const ICONS = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: AlertTriangle,
  offline: WifiOff,
} as const;

export type AlertTone = keyof typeof ICONS;

const TONE_CLASS: Record<AlertTone, string> = {
  info: "border-border bg-muted",
  success: "border-success bg-success-soft",
  warning: "border-approval bg-approval-soft",
  danger: "border-danger bg-danger-soft",
  offline: "border-approval bg-approval-soft",
};

const ICON_CLASS: Record<AlertTone, string> = {
  info: "text-muted-foreground",
  success: "text-success",
  warning: "text-approval",
  danger: "text-danger",
  offline: "text-approval",
};

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: AlertTone;
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon = ICONS[tone];
  const urgent = tone === "danger" || tone === "warning" || tone === "offline";

  return (
    <div
      role={urgent ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2.5 rounded-md border px-3.5 py-3",
        TONE_CLASS[tone],
        className,
      )}
    >
      <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", ICON_CLASS[tone])} />
      <div className="min-w-0 flex-1 text-sm text-foreground">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={cn(title && "mt-0.5")}>{children}</div> : null}
      </div>
      {action}
    </div>
  );
}
