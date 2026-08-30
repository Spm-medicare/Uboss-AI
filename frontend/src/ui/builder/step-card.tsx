"use client";

import { ChevronDown, GripVertical, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import type { CurrentStepInput } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Suggest } from "@/ui/builder/suggest";

/**
 * One step of the work as it happens today — the approved workbook's fourteen columns.
 *
 * **A card, not a table row.** PLAN §6 asks for *"Repeatable WHO, INPUT and step cards"*, and the
 * reason is visible the moment you try the alternative: fourteen columns on a screen means either
 * a horizontal scroll where the person loses which row they are on, or columns squeezed to
 * forty pixels. The card keeps the workbook's own grouping — WHO, WHEN, WHAT, INPUT, WHERE,
 * OUTPUT — which is how the sheet is already organised and how people describe their own work.
 *
 * Collapsed, it shows a one-line summary in the person's own words. A twenty-step process is
 * reviewable that way and unreadable as twenty open cards.
 */
export function StepCard({
  step,
  index,
  total,
  lists,
  disabled,
  onChange,
  onRemove,
  onMove,
}: {
  step: CurrentStepInput;
  index: number;
  total: number;
  lists: {
    triggers: string[];
    frequencies: string[];
    work_places: string[];
    problems: string[];
    approvals: string[];
  };
  disabled: boolean;
  onChange: (next: CurrentStepInput) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const t = useTranslations("objective");
  const [open, setOpen] = useState(index === 0);
  const panelId = useId();

  const set = <K extends keyof CurrentStepInput>(key: K, value: string) =>
    onChange({ ...step, [key]: value || null });

  const summary =
    step.what_exact_work?.trim() ||
    step.who_role?.trim() ||
    step.who_person?.trim() ||
    t("stepUnnamed");

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
          className="grid size-6 shrink-0 place-items-center rounded-md bg-human-soft text-xs font-semibold text-human"
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
          {!open && step.current_problem && step.current_problem !== "No problem" ? (
            <Badge tone="approval">{step.current_problem}</Badge>
          ) : null}
          {!open && step.time_taken ? (
            <span className="shrink-0 text-xs text-muted-foreground">{step.time_taken}</span>
          ) : null}
        </button>

        <span className="flex shrink-0 items-center">
          {/*  Buttons rather than drag-and-drop. A keyboard user can reorder with these, and
              dragging on a phone competes with scrolling. */}
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
              onChange={(value) => set("who_person", value)}
              disabled={disabled}
            />
            <Suggest
              label={t("whoRole")}
              value={step.who_role ?? ""}
              onChange={(value) => set("who_role", value)}
              disabled={disabled}
            />
          </Group>

          <Group label={t("when")} tone="hybrid">
            <Suggest
              label={t("whenTrigger")}
              value={step.when_trigger ?? ""}
              options={lists.triggers}
              onChange={(value) => set("when_trigger", value)}
              disabled={disabled}
            />
            <Suggest
              label={t("whenFrequency")}
              value={step.when_frequency ?? ""}
              options={lists.frequencies}
              onChange={(value) => set("when_frequency", value)}
              disabled={disabled}
            />
          </Group>

          <Group label={t("what")} tone="primary" full>
            <Suggest
              label={t("whatExactWork")}
              value={step.what_exact_work ?? ""}
              multiline
              onChange={(value) => set("what_exact_work", value)}
              disabled={disabled}
            />
          </Group>

          <Group label={t("input")} tone="human">
            <Suggest
              label={t("inputUsed")}
              value={step.input_used ?? ""}
              onChange={(value) => set("input_used", value)}
              disabled={disabled}
            />
            <Suggest
              label={t("inputFrom")}
              value={step.input_received_from ?? ""}
              onChange={(value) => set("input_received_from", value)}
              disabled={disabled}
            />
          </Group>

          <Group label={t("where")} tone="hybrid">
            <Suggest
              label={t("whereDone")}
              value={step.where_done ?? ""}
              options={lists.work_places}
              onChange={(value) => set("where_done", value)}
              disabled={disabled}
            />
            <Suggest
              label={t("timeTaken")}
              value={step.time_taken ?? ""}
              onChange={(value) => set("time_taken", value)}
              disabled={disabled}
            />
          </Group>

          <Group label={t("output")} tone="success">
            <Suggest
              label={t("outputProduced")}
              value={step.output_produced ?? ""}
              onChange={(value) => set("output_produced", value)}
              disabled={disabled}
            />
            <Suggest
              label={t("outputSentTo")}
              value={step.output_sent_to ?? ""}
              onChange={(value) => set("output_sent_to", value)}
              disabled={disabled}
            />
          </Group>

          <Group label={t("todayAndApproval")} tone="approval">
            <Suggest
              label={t("currentProblem")}
              value={step.current_problem ?? ""}
              options={lists.problems}
              onChange={(value) => set("current_problem", value)}
              disabled={disabled}
            />
            <Suggest
              label={t("approval")}
              value={step.approval ?? ""}
              options={lists.approvals}
              onChange={(value) => set("approval", value)}
              disabled={disabled}
            />
          </Group>
        </div>
      ) : null}
    </li>
  );
}

/**
 * One of the workbook's own groupings — WHO, WHEN, WHAT and the rest.
 *
 * The tone follows PLAN §29's vocabulary rather than being picked for looks: blue for the human
 * parts, teal where a person and a system meet, green for what comes out, amber for the problem
 * and the approval. The label carries the meaning; the colour only reinforces it.
 */
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
