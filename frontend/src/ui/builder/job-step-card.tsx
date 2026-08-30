"use client";

import { Bot, ChevronDown, GripVertical, Trash2, User, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import type { JobStepInput, StepMode } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Suggest } from "@/ui/builder/suggest";

/**
 * One step of Form 3 — the workbook's sixteen columns, as a card.
 *
 * Same reasoning as the Objective's step card: sixteen columns on a screen is either a horizontal
 * scroll where somebody loses their row, or columns squeezed to nothing. PLAN §6 already asked for
 * *"repeatable WHO, INPUT and step cards"*, and the sheet's own grouping — WHO, WHEN, WHAT, INPUT,
 * HOW, WHERE, OUTPUT — is how people describe their work out loud.
 *
 * Two fields carry more weight than the rest and are placed accordingly:
 *
 * * **HOW** is what separates a Job from an Objective. The objective says what happens; the job
 *   says how. It gets the workbook's own list of twenty-two verbs.
 * * **If missing or wrong** is what makes a method runnable rather than merely written down. It
 *   sits beside the mode, because an unattended step without it is the one combination that fails
 *   badly — and the card marks that combination rather than waiting for the publish screen.
 */

const MODES: Record<StepMode, { icon: typeof User; tone: "human" | "ai" | "hybrid" }> = {
  human: { icon: User, tone: "human" },
  ai_agent: { icon: Bot, tone: "ai" },
  hybrid: { icon: Users, tone: "hybrid" },
};

export function JobStepCard({
  step,
  index,
  total,
  lists,
  disabled,
  onChange,
  onRemove,
  onMove,
}: {
  step: JobStepInput;
  index: number;
  total: number;
  lists: {
    triggers: string[];
    frequencies: string[];
    work_places: string[];
    methods: string[];
    approval_timings: string[];
    missing_actions: string[];
    output_formats: string[];
  };
  disabled: boolean;
  onChange: (next: JobStepInput) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const t = useTranslations("job");
  const [open, setOpen] = useState(index === 0);
  const panelId = useId();

  const mode = (step.mode ?? "human") as StepMode;
  const Icon = MODES[mode].icon;
  const set = <K extends keyof JobStepInput>(key: K, value: string) =>
    onChange({ ...step, [key]: value || null });

  //  An unattended step with no fallback. Marked here, where somebody can fix it, rather than
  //  only on the publish screen where they are already finished.
  const unguarded =
    (mode === "ai_agent" || mode === "hybrid") && !(step.if_missing_or_wrong ?? "").trim();

  const summary =
    step.what_exact_work?.trim() || step.who_role?.trim() || t("stepUnnamed");

  return (
    <li
      className={cn(
        "overflow-hidden rounded-lg border bg-card transition-colors duration-150",
        "motion-reduce:transition-none",
        open ? "border-[var(--ub-brand)]" : "border-border",
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2.5">
        <span
          aria-hidden
          className={cn(
            "grid size-6 shrink-0 place-items-center rounded-md text-xs font-semibold",
            mode === "human" && "bg-human-soft text-human",
            mode === "ai_agent" && "bg-ai-soft text-ai",
            mode === "hybrid" && "bg-hybrid-soft text-hybrid",
          )}
        >
          {index + 1}
        </span>

        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls={panelId}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
          )}
        >
          <ChevronDown
            aria-hidden
            className={cn(
              "size-4 shrink-0 text-muted-foreground transition-transform duration-150",
              "motion-reduce:transition-none",
              !open && "-rotate-90",
            )}
          />
          <span className="min-w-0 flex-1 truncate text-sm">{summary}</span>
          {!open && step.how_exact_method ? (
            <Badge tone="neutral">{step.how_exact_method}</Badge>
          ) : null}
          {!open && unguarded ? <Badge tone="approval">{t("noFallback")}</Badge> : null}
          <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
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
          <Button
            variant="ghost"
            size="sm"
            className="size-8 px-0 text-muted-foreground hover:text-danger"
            aria-label={t("removeStep", { step: index + 1 })}
            disabled={disabled}
            onClick={onRemove}
            icon={<Trash2 className="size-3.5" />}
          />
        </span>
      </div>

      {open ? (
        <div id={panelId} className="space-y-4 border-t border-border px-4 py-4">
          <Group label={t("who")} tone="human">
            <Suggest
              label={t("whoPerson")}
              value={step.who_person ?? ""}
              disabled={disabled}
              onChange={(value) => set("who_person", value)}
            />
            <Suggest
              label={t("whoRole")}
              value={step.who_role ?? ""}
              disabled={disabled}
              onChange={(value) => set("who_role", value)}
            />
          </Group>

          <Group label={t("when")} tone="hybrid">
            <Suggest
              label={t("whenTrigger")}
              value={step.when_trigger ?? ""}
              options={lists.triggers}
              disabled={disabled}
              onChange={(value) => set("when_trigger", value)}
            />
            <Suggest
              label={t("whenFrequency")}
              value={step.when_frequency ?? ""}
              options={lists.frequencies}
              disabled={disabled}
              onChange={(value) => set("when_frequency", value)}
            />
          </Group>

          <Group label={t("what")} tone="primary" full>
            <Suggest
              label={t("whatExactWork")}
              value={step.what_exact_work ?? ""}
              multiline
              disabled={disabled}
              onChange={(value) => set("what_exact_work", value)}
            />
          </Group>

          <Group label={t("input")} tone="human">
            <Suggest
              label={t("inputExact")}
              value={step.input_exact ?? ""}
              disabled={disabled}
              onChange={(value) => set("input_exact", value)}
            />
            <Suggest
              label={t("inputFoundWhere")}
              value={step.input_found_where ?? ""}
              options={lists.work_places}
              disabled={disabled}
              onChange={(value) => set("input_found_where", value)}
            />
          </Group>

          {/*  HOW is the column that separates a Job from an Objective, and it gets the
              workbook's own list of verbs rather than a free box. */}
          <Group label={t("how")} tone="primary">
            <Suggest
              label={t("howExactMethod")}
              value={step.how_exact_method ?? ""}
              options={lists.methods}
              disabled={disabled}
              onChange={(value) => set("how_exact_method", value)}
            />
            <Suggest
              label={t("wherePerformed")}
              value={step.where_performed ?? ""}
              options={lists.work_places}
              disabled={disabled}
              onChange={(value) => set("where_performed", value)}
            />
          </Group>

          <Group label={t("rule")} tone="approval" full>
            <Suggest
              label={t("ruleFormulaCheck")}
              value={step.rule_formula_check ?? ""}
              multiline
              disabled={disabled}
              placeholder={t("rulePlaceholder")}
              onChange={(value) => set("rule_formula_check", value)}
            />
          </Group>

          <Group label={t("output")} tone="success">
            <Suggest
              label={t("outputProduced")}
              value={step.output ?? ""}
              options={lists.output_formats}
              disabled={disabled}
              onChange={(value) => set("output", value)}
            />
            <Suggest
              label={t("outputDestination")}
              value={step.output_destination ?? ""}
              disabled={disabled}
              onChange={(value) => set("output_destination", value)}
            />
          </Group>

          <Group label={t("controls")} tone="approval">
            <Suggest
              label={t("approval")}
              value={step.approval ?? ""}
              options={lists.approval_timings}
              disabled={disabled}
              onChange={(value) => set("approval", value)}
            />
            <Suggest
              label={t("timeTaken")}
              value={step.time_taken ?? ""}
              disabled={disabled}
              onChange={(value) => set("time_taken", value)}
            />
          </Group>

          <div>
            <p className="mb-1.5 text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {t("doneBy")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(Object.keys(MODES) as StepMode[]).map((option) => {
                const OptionIcon = MODES[option].icon;
                return (
                  <button
                    key={option}
                    type="button"
                    disabled={disabled}
                    aria-pressed={mode === option}
                    onClick={() => onChange({ ...step, mode: option })}
                    className={cn(
                      "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                      "transition-colors duration-150 motion-reduce:transition-none",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                      "disabled:cursor-not-allowed disabled:opacity-60",
                      mode === option
                        ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                        : "border-border bg-card hover:bg-accent",
                    )}
                  >
                    <OptionIcon aria-hidden className="size-3" />
                    {t(`mode.${option}`)}
                  </button>
                );
              })}
            </div>
          </div>

          {/*  Beside the mode, because the two together are what decides whether this step can
              fail safely. Highlighted when it is missing on an automated step. */}
          <div
            className={cn(
              "rounded-md border p-3",
              unguarded ? "border-approval bg-approval-soft" : "border-border",
            )}
          >
            <Suggest
              label={t("ifMissingOrWrong")}
              value={step.if_missing_or_wrong ?? ""}
              options={lists.missing_actions}
              disabled={disabled}
              onChange={(value) => set("if_missing_or_wrong", value)}
            />
            {unguarded ? (
              <p className="mt-1.5 text-xs text-approval">{t("noFallbackHelp")}</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function Group({
  label,
  tone,
  full = false,
  children,
}: {
  label: string;
  tone: "human" | "hybrid" | "primary" | "success" | "approval";
  full?: boolean;
  children: React.ReactNode;
}) {
  const tones: Record<string, string> = {
    human: "text-human",
    hybrid: "text-hybrid",
    primary: "text-primary",
    success: "text-success",
    approval: "text-approval",
  };

  return (
    <div>
      <p
        className={cn(
          "mb-1.5 text-[0.6875rem] font-semibold uppercase tracking-wide",
          tones[tone],
        )}
      >
        {label}
      </p>
      <div className={cn("grid gap-3", full ? "grid-cols-1" : "sm:grid-cols-2")}>
        {children}
      </div>
    </div>
  );
}
