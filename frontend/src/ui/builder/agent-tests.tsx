"use client";

import { CheckCircle2, CircleDashed, Lock, ShieldCheck, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type {
  AgentPublishGate,
  AgentPublishWarning,
  SandboxTestInput,
  SandboxTestList,
  SandboxTestRead,
} from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Alert, Badge, Button, Field, Textarea } from "@/ui";

/**
 * Form 4 section C, and the two gates `PLAN.md` §9 makes a publish depend on.
 *
 * > Tests and permission review are publish gates.
 *
 * **The gates come from the server and are rendered as it sent them.** Each one says whether it
 * passed and, when it did not, what would clear it — in the gate's own sentence. Nothing here
 * re-derives a verdict: a screen that decided for itself whether an agent was publishable would
 * be a second implementation of the rule, and the one on screen is the one people would trust.
 *
 * **There is no sandbox runtime yet.** Gate 7 brings execution, so a status is recorded by the
 * person who ran the test. The screen says so rather than implying a button ran something, and
 * a result must carry what actually happened before it can be anything but *Not Run*.
 */

const STATUS_ICON = {
  pass: CheckCircle2,
  fail: XCircle,
  blocked: Lock,
  not_run: CircleDashed,
} as const;

const STATUS_TONE: Record<string, "success" | "danger" | "approval" | "neutral"> = {
  pass: "success",
  fail: "danger",
  blocked: "approval",
  not_run: "neutral",
};

export function SandboxTests({
  tests,
  disabled,
  saving,
  onSave,
}: {
  tests: SandboxTestList;
  disabled: boolean;
  saving: boolean;
  onSave: (next: SandboxTestInput[]) => void;
}) {
  const t = useTranslations("agent");

  //  The five rows the sheet prints, whether or not they have been written yet. `missing` and a
  //  `Not Run` status are different answers and the server reports both.
  const written = tests.tests ?? [];
  const missing = tests.missing ?? [];
  const rows: SandboxTestInput[] = [
    ...written.map((row) => ({
      kind: row.kind,
      sample_situation: row.sample_situation,
      expected_result: row.expected_result,
      status: row.status,
      actual_result: row.actual_result,
    })),
    ...missing.map((kind) => ({ kind, status: "not_run" as const })),
  ];

  const [draft, setDraft] = useState<SandboxTestInput[]>(rows);
  const labels = new Map(written.map((row) => [row.kind, row.label]));

  const set = (kind: string, patch: Partial<SandboxTestInput>) =>
    setDraft((current) =>
      current.map((row) => (row.kind === kind ? { ...row, ...patch } : row)),
    );

  const dirty = JSON.stringify(draft) !== JSON.stringify(rows);

  return (
    <div className="space-y-3">
      <Alert tone={tests.passed === tests.total ? "success" : "info"}>
        {t("testsProgress", { passed: tests.passed, total: tests.total })}
      </Alert>

      <p className="text-sm text-muted-foreground">{t("testsIntro")}</p>

      <ul className="space-y-3">
        {draft.map((row) => (
          <li key={row.kind}>
            <TestRow
              row={row}
              label={labels.get(row.kind) ?? t(`test.${row.kind}`)}
              saved={written.find((written_) => written_.kind === row.kind)}
              disabled={disabled}
              onChange={(patch) => set(row.kind, patch)}
            />
          </li>
        ))}
      </ul>

      {!disabled ? (
        <Button
          variant="secondary"
          busy={saving}
          disabled={!dirty}
          onClick={() => onSave(draft)}
        >
          {t("saveTests")}
        </Button>
      ) : null}
    </div>
  );
}

function TestRow({
  row,
  label,
  saved,
  disabled,
  onChange,
}: {
  row: SandboxTestInput;
  label: string;
  saved: SandboxTestRead | undefined;
  disabled: boolean;
  onChange: (patch: Partial<SandboxTestInput>) => void;
}) {
  const t = useTranslations("agent");
  const status = row.status ?? "not_run";
  const Icon = STATUS_ICON[status as keyof typeof STATUS_ICON] ?? CircleDashed;

  //  The schema refuses a result with no observation, so the control that would produce one is
  //  disabled and labelled rather than left to fail at the database.
  const observed = Boolean(row.actual_result?.trim());

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Icon
          aria-hidden
          className={cn(
            "size-4",
            status === "pass" && "text-success",
            status === "fail" && "text-danger",
            status === "blocked" && "text-approval",
            status === "not_run" && "text-muted-foreground",
          )}
        />
        <p className="text-sm font-medium">{label}</p>
        <Badge tone={STATUS_TONE[status] ?? "neutral"}>
          {saved?.status_label ?? t(`testStatus.${status}`)}
        </Badge>
        {/*  Who observed it and when — stamped by the server, so this is evidence rather than a
            checkbox somebody ticked. */}
        {saved?.run_at && saved.run_by_name ? (
          <span className="text-xs text-muted-foreground">
            {t("ranBy", {
              name: saved.run_by_name,
              when: new Date(saved.run_at).toLocaleString(),
            })}
          </span>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("field.sampleSituation")}>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={row.sample_situation ?? ""}
              disabled={disabled}
              onChange={(event) =>
                onChange({ sample_situation: event.target.value || null })
              }
            />
          )}
        </Field>
        <Field label={t("field.expectedResult")}>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={row.expected_result ?? ""}
              disabled={disabled}
              onChange={(event) =>
                onChange({ expected_result: event.target.value || null })
              }
            />
          )}
        </Field>
      </div>

      <div className="mt-3">
        <Field label={t("field.actualResult")} hint={t("actualResultHint")}>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={row.actual_result ?? ""}
              disabled={disabled}
              onChange={(event) => onChange({ actual_result: event.target.value || null })}
            />
          )}
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {(["not_run", "pass", "fail", "blocked"] as const).map((option) => {
          //  Anything but `Not Run` needs an observation. Disabled with a reason beside it, never
          //  a button that fails when pressed.
          const allowed = option === "not_run" || observed;
          return (
            <button
              key={option}
              type="button"
              aria-pressed={status === option}
              disabled={disabled || !allowed}
              onClick={() => onChange({ status: option })}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors duration-150",
                "motion-reduce:transition-none disabled:cursor-not-allowed disabled:opacity-50",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                status === option
                  ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-accent",
              )}
            >
              {t(`testStatus.${option}`)}
            </button>
          );
        })}
        {!observed ? (
          <span className="self-center text-xs text-muted-foreground">
            {t("needsObservation")}
          </span>
        ) : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------- the gates

export function PublishGates({
  gates,
  warnings,
  nextAction,
}: {
  gates: AgentPublishGate[];
  warnings: AgentPublishWarning[];
  nextAction: string;
}) {
  const t = useTranslations("agent");

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {gates.map((gate) => (
          <li
            key={gate.gate}
            className={cn(
              "flex gap-2 rounded-lg border p-3",
              gate.passed ? "border-success bg-success-soft" : "border-approval bg-approval-soft",
            )}
          >
            {gate.passed ? (
              <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
            ) : (
              <Lock aria-hidden className="mt-0.5 size-4 shrink-0 text-approval" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-medium">{gate.name}</p>
              {/*  The gate's own sentence. It says what would clear it, not merely that it is
                  closed — a screen that said "blocked" alone sends somebody hunting. */}
              <p className="mt-0.5 text-sm text-muted-foreground">{gate.reason}</p>
            </div>
          </li>
        ))}
      </ul>

      {warnings.length > 0 ? (
        <section aria-labelledby="agent-warnings" className="space-y-2">
          <h3 id="agent-warnings" className="text-sm font-medium">
            {t("warningsTitle", { count: warnings.length })}
          </h3>
          {/*  Warnings are shown and never hidden, and they never block. §9 names two gates; a
              third invented here would be a rule nobody approved. */}
          <ul className="space-y-1.5">
            {warnings.map((warning) => (
              <li key={warning.code}>
                <Alert tone="warning">{warning.message}</Alert>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {nextAction ? (
        <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
          <span className="font-medium">{t("nextAction")}</span> {nextAction}
        </p>
      ) : null}
    </div>
  );
}
