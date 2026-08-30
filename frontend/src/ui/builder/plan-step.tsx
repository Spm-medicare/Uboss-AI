"use client";

import {
  Bot,
  ChevronDown,
  Copy,
  GripVertical,
  Merge,
  ShieldCheck,
  Sparkles,
  Trash2,
  User,
  Users,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import type { Step } from "@/lib/api/objective-plan";
import type { StepKind } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Suggest } from "@/ui/builder/suggest";

/**
 * One block of the proposed execution graph.
 *
 * PLAN §29 fixes the colours and they are not decoration: **violet for AI, blue for human, teal
 * for hybrid, amber for approval, green for output**. A person scanning a plan is asking one
 * question — how much of this is a machine doing it unattended — and the kind is the answer, so
 * the kind is what the eye lands on first.
 *
 * Two things this card shows that a plainer one would not, and both are what makes a proposal
 * reviewable rather than merely visible:
 *
 * * **Why the model put it there.** Its own words, beside the step. A reviewer who can see only
 *   the conclusion cannot disagree with the reasoning.
 * * **Whether a person has changed it.** `source = ai` and `edited` together are PLAN §7's
 *   "compare AI/human changes", and they are on the card rather than in a report because that is
 *   where somebody is when the question occurs to them.
 */

const KINDS: Record<
  StepKind,
  { icon: typeof User; tone: string; ring: string; badge: "human" | "ai" | "hybrid" | "approval" | "success" }
> = {
  human: { icon: User, tone: "text-human", ring: "bg-human-soft", badge: "human" },
  ai_agent: { icon: Bot, tone: "text-ai", ring: "bg-ai-soft", badge: "ai" },
  hybrid: { icon: Users, tone: "text-hybrid", ring: "bg-hybrid-soft", badge: "hybrid" },
  approval: {
    icon: ShieldCheck,
    tone: "text-approval",
    ring: "bg-approval-soft",
    badge: "approval",
  },
  output: { icon: Sparkles, tone: "text-success", ring: "bg-success-soft", badge: "success" },
};

export function PlanStep({
  step,
  index,
  total,
  steps,
  disabled,
  onChange,
  onRemove,
  onDuplicate,
  onMerge,
  onMove,
  onDependencies,
}: {
  step: Step;
  index: number;
  total: number;
  /** Everything in the plan, so dependencies and merges can name their target. */
  steps: Step[];
  disabled: boolean;
  onChange: (changes: Record<string, unknown>) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  onMerge: (intoStepId: string) => void;
  onMove: (direction: -1 | 1) => void;
  onDependencies: (dependsOn: string[]) => void;
}) {
  const t = useTranslations("plan");
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const kind = KINDS[step.kind];
  const Icon = kind.icon;

  const others = steps.filter((other) => other.id !== step.id);
  const waitsFor = steps.filter((other) => step.depends_on.includes(other.id));

  return (
    <li
      className={cn(
        "overflow-hidden rounded-lg border bg-card transition-colors duration-150",
        "motion-reduce:transition-none",
        open ? "border-[var(--ub-brand)]" : "border-border",
      )}
    >
      <div className="flex items-start gap-3 p-3">
        <span
          aria-hidden
          className={cn(
            "grid size-8 shrink-0 place-items-center rounded-lg",
            kind.ring,
            kind.tone,
          )}
        >
          <Icon className="size-4" />
        </span>

        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls={panelId}
          className={cn(
            "min-w-0 flex-1 rounded-md text-left",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
          )}
        >
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-xs tabular-nums text-muted-foreground">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="min-w-0 flex-1 text-sm font-medium">{step.title}</span>
            <Badge tone={kind.badge}>{t(`kind.${step.kind}`)}</Badge>
            {step.source === "ai" && step.edited ? (
              //  §7's comparison, on the card. Not a warning — a person correcting a proposal is
              //  the product working, and the badge records it rather than complaining about it.
              <Badge tone="neutral">{t("aiEdited")}</Badge>
            ) : null}
            {step.source === "human" ? <Badge tone="neutral">{t("yours")}</Badge> : null}
          </span>

          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            {step.responsible_role ? <span>{step.responsible_role}</span> : null}
            {waitsFor.length > 0 ? (
              <span>
                {t("waitsFor", {
                  steps: waitsFor
                    .map((other) => String(steps.indexOf(other) + 1).padStart(2, "0"))
                    .join(", "),
                })}
              </span>
            ) : null}
            {step.replaces_current_step ? (
              <span>{t("replacesStep", { step: step.replaces_current_step })}</span>
            ) : null}
          </span>
        </button>

        <span className="flex shrink-0 items-center">
          <Button
            variant="ghost"
            size="sm"
            className="size-8 px-0"
            aria-label={t("moveUp", { step: index + 1 })}
            disabled={disabled || index === 0}
            onClick={() => onMove(-1)}
            icon={<GripVertical className="size-3.5 rotate-90" />}
          />
          <Button
            variant="ghost"
            size="sm"
            className="size-8 px-0"
            aria-label={t("moveDown", { step: index + 1 })}
            disabled={disabled || index === total - 1}
            onClick={() => onMove(1)}
            icon={<GripVertical className="size-3.5 -rotate-90" />}
          />
          <ChevronDown
            aria-hidden
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-150",
              "motion-reduce:transition-none",
              !open && "-rotate-90",
            )}
          />
        </span>
      </div>

      {/*  The model's reasoning, visible without opening the card. A reviewer who can only see
          the conclusion cannot disagree with the reasoning. */}
      {step.rationale && !open ? (
        <p className="border-t border-border px-3 py-2 text-xs italic text-muted-foreground">
          {step.rationale}
        </p>
      ) : null}

      {open ? (
        <div id={panelId} className="space-y-4 border-t border-border p-4">
          <Suggest
            label={t("title")}
            value={step.title}
            disabled={disabled}
            onChange={(value) => onChange({ title: value })}
          />

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t("kindLabel")}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {(Object.keys(KINDS) as StepKind[]).map((option) => {
                  const style = KINDS[option];
                  const OptionIcon = style.icon;
                  return (
                    <button
                      key={option}
                      type="button"
                      disabled={disabled}
                      aria-pressed={step.kind === option}
                      onClick={() => onChange({ kind: option })}
                      className={cn(
                        "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                        "transition-colors duration-150 motion-reduce:transition-none",
                        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                        "disabled:cursor-not-allowed disabled:opacity-60",
                        step.kind === option
                          ? cn("border-current", style.ring, style.tone)
                          : "border-border bg-card hover:bg-accent",
                      )}
                    >
                      <OptionIcon aria-hidden className="size-3" />
                      {t(`kind.${option}`)}
                    </button>
                  );
                })}
              </div>
            </div>

            <Suggest
              label={t("responsibleRole")}
              value={step.responsible_role ?? ""}
              disabled={disabled}
              onChange={(value) => onChange({ responsible_role: value || null })}
            />
          </div>

          <Suggest
            label={t("detail")}
            value={step.detail ?? ""}
            multiline
            disabled={disabled}
            onChange={(value) => onChange({ detail: value || null })}
          />

          {step.rationale ? (
            <div className="rounded-md bg-muted/60 px-3 py-2">
              <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                {step.source === "ai" ? t("whyProposed") : t("note")}
              </p>
              <p className="mt-0.5 text-sm text-muted-foreground">{step.rationale}</p>
            </div>
          ) : null}

          <fieldset disabled={disabled}>
            <legend className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("dependsOnLabel")}
            </legend>
            {others.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("nothingToWaitFor")}</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {others.map((other) => {
                  const on = step.depends_on.includes(other.id);
                  return (
                    <button
                      key={other.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() =>
                        onDependencies(
                          on
                            ? step.depends_on.filter((id) => id !== other.id)
                            : [...step.depends_on, other.id],
                        )
                      }
                      className={cn(
                        "rounded-md border px-2 py-1 text-xs",
                        "transition-colors duration-150 motion-reduce:transition-none",
                        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                        on
                          ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                          : "border-border bg-card hover:bg-accent",
                      )}
                    >
                      {String(steps.indexOf(other) + 1).padStart(2, "0")} {other.title}
                    </button>
                  );
                })}
              </div>
            )}
          </fieldset>

          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
            <Button
              size="sm"
              variant="ghost"
              disabled={disabled}
              icon={<Copy className="size-3.5" />}
              onClick={onDuplicate}
            >
              {t("duplicate")}
            </Button>

            {others.length > 0 ? (
              <label className="flex items-center gap-1.5 text-sm">
                <Merge aria-hidden className="size-3.5 text-muted-foreground" />
                <span className="sr-only">{t("mergeInto")}</span>
                <select
                  disabled={disabled}
                  value=""
                  onChange={(event) => {
                    if (event.target.value) onMerge(event.target.value);
                  }}
                  className="h-8 rounded-md border border-border bg-card px-2 text-sm disabled:opacity-60"
                >
                  <option value="">{t("mergeInto")}</option>
                  {others.map((other) => (
                    <option key={other.id} value={other.id}>
                      {String(steps.indexOf(other) + 1).padStart(2, "0")} {other.title}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <Button
              size="sm"
              variant="ghost"
              className="ml-auto text-muted-foreground hover:text-danger"
              disabled={disabled}
              icon={<Trash2 className="size-3.5" />}
              onClick={onRemove}
            >
              {t("remove")}
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}
