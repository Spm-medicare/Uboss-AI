"use client";

import { AlertTriangle, Check, Loader2, Minus } from "lucide-react";
import { useTranslations } from "next-intl";

import type { AnalysisRead, StageRead } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTime } from "@/lib/format";

/**
 * The real analysis timeline — PLAN §6 puts it between approving the analysis and editing its
 * output, and the word doing the work is *real*.
 *
 * Every row here is a database row written when that stage actually ran. Nothing advances on a
 * timer, nothing is interpolated, and a stage that has not started is drawn as not started rather
 * than as pending-and-probably-fine. `ui/README.md` forbids fake progress; this is what the
 * honest version looks like.
 *
 * That also means the timeline is worth reading *after* a failure. It shows the three stages that
 * did succeed and the one that stopped, which is the difference between "it did not work" and
 * knowing where to look.
 */
export function AnalysisTimeline({
  analysis,
  timeZone,
}: {
  analysis: AnalysisRead;
  timeZone: string | undefined;
}) {
  const t = useTranslations("plan");
  const format = contextFor(timeZone);
  const stages = analysis.stages ?? [];

  return (
    <ol className="space-y-0">
      {stages.map((stage, index) => (
        <li key={stage.stage} className="flex gap-3">
          <div className="flex flex-col items-center">
            <StageMark state={stage.state} />
            {index < stages.length - 1 ? (
              <span
                aria-hidden
                className={cn(
                  "w-px flex-1",
                  stage.state === "done" ? "bg-success/40" : "bg-border",
                )}
              />
            ) : null}
          </div>

          <div className={cn("min-w-0 flex-1", index < stages.length - 1 && "pb-4")}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <p
                className={cn(
                  "text-sm",
                  stage.state ? "font-medium" : "text-muted-foreground",
                )}
              >
                {t(`stage.${stage.stage}`)}
              </p>
              {stage.at ? (
                <time
                  dateTime={stage.at}
                  className="text-xs tabular-nums text-muted-foreground"
                >
                  {formatDateTime(stage.at, format)}
                </time>
              ) : null}
            </div>
            {stage.detail ? (
              <p
                className={cn(
                  "mt-0.5 text-sm",
                  stage.state === "failed" ? "text-danger" : "text-muted-foreground",
                )}
              >
                {stage.detail}
              </p>
            ) : (
              !stage.state && (
                <p className="mt-0.5 text-sm text-muted-foreground">{t("notStarted")}</p>
              )
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function StageMark({ state }: { state: StageRead["state"] }) {
  const base =
    "grid size-6 shrink-0 place-items-center rounded-full border-2 bg-background";

  switch (state) {
    case "done":
      return (
        <span aria-hidden className={cn(base, "border-success text-success")}>
          <Check className="size-3.5" />
        </span>
      );
    case "running":
      return (
        <span aria-hidden className={cn(base, "border-primary text-primary")}>
          <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
        </span>
      );
    case "failed":
      return (
        <span aria-hidden className={cn(base, "border-danger text-danger")}>
          <AlertTriangle className="size-3.5" />
        </span>
      );
    case "skipped":
      return (
        <span aria-hidden className={cn(base, "border-border text-muted-foreground")}>
          <Minus className="size-3.5" />
        </span>
      );
    default:
      //  Not started. Hollow, so it reads as ahead rather than as something that went wrong.
      return <span aria-hidden className={cn(base, "border-border")} />;
  }
}
