"use client";

import {
  ChevronDown,
  KeyRound,
  Lock,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import type {
  AgentStepInput,
  EscalationRuleInput,
  Situation,
  IoSchemaInput,
  KnowledgeSourceInput,
  ToolInput,
  ToolRead,
} from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Alert, Badge, Button, Field, Input } from "@/ui";
import { Suggest } from "@/ui/builder/suggest";

/**
 * The Agent form's repeatable sections — Form 4's section A and section B, and §9's groups 4, 6
 * and 7.
 *
 * Cards rather than table rows, for the reason the Job Builder already found: nine columns on a
 * screen means either a horizontal scroll where the person loses which row they are on, or
 * columns squeezed to forty pixels. The card keeps the sheet's own grouping.
 */

// ------------------------------------------------------------------- section A: design rows

export function DesignSteps({
  steps,
  approvals,
  disabled,
  onChange,
}: {
  steps: AgentStepInput[];
  approvals: string[];
  disabled: boolean;
  onChange: (next: AgentStepInput[]) => void;
}) {
  const t = useTranslations("agent");

  const set = (index: number, next: AgentStepInput) =>
    onChange(steps.map((step, at) => (at === index ? next : step)));

  const add = () =>
    onChange([...steps, { position: steps.length + 1 }]);

  const remove = (index: number) =>
    onChange(
      steps
        .filter((_, at) => at !== index)
        .map((step, at) => ({ ...step, position: at + 1 })),
    );

  return (
    <div className="space-y-3">
      {steps.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {t("noSteps")}
        </p>
      ) : (
        <ol className="space-y-3">
          {steps.map((step, index) => (
            <li key={step.position}>
              <DesignStepCard
                step={step}
                index={index}
                approvals={approvals}
                disabled={disabled}
                onChange={(next) => set(index, next)}
                onRemove={() => remove(index)}
              />
            </li>
          ))}
        </ol>
      )}

      {!disabled ? (
        <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={add}>
          {t("addStep")}
        </Button>
      ) : null}
    </div>
  );
}

function DesignStepCard({
  step,
  index,
  approvals,
  disabled,
  onChange,
  onRemove,
}: {
  step: AgentStepInput;
  index: number;
  approvals: string[];
  disabled: boolean;
  onChange: (next: AgentStepInput) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("agent");
  const [open, setOpen] = useState(index === 0);
  const panelId = useId();

  const set = (key: keyof AgentStepInput, value: string) =>
    onChange({ ...step, [key]: value || null });

  const summary = step.agent_action?.trim() || step.output?.trim() || "";

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center gap-2 p-3">
        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
          {step.position}
        </span>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]"
        >
          <span className={cn("min-w-0 flex-1 truncate text-sm", !summary && "text-muted-foreground")}>
            {summary || t("stepUnnamed")}
          </span>
          {/*  A prohibition is the thing a reviewer scans for, so it is visible while collapsed. */}
          {step.must_never_do ? <Badge tone="approval">{t("hasProhibition")}</Badge> : null}
          <ChevronDown
            aria-hidden
            className={cn("size-4 shrink-0 transition-transform duration-150", open && "rotate-180")}
          />
        </button>
        {!disabled ? (
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="size-3.5" />}
            onClick={onRemove}
          >
            <span className="sr-only">{t("removeStep")}</span>
          </Button>
        ) : null}
      </div>

      {open ? (
        <div id={panelId} className="space-y-3 border-t border-border p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Suggest
              label={t("field.inputUsed")}
              value={step.input_used ?? ""}
              disabled={disabled}
              onChange={(value) => set("input_used", value)}
            />
            <Suggest
              label={t("field.inputSource")}
              value={step.input_source ?? ""}
              disabled={disabled}
              onChange={(value) => set("input_source", value)}
            />
          </div>

          <Suggest
            label={t("field.agentAction")}
            value={step.agent_action ?? ""}
            multiline
            disabled={disabled}
            onChange={(value) => set("agent_action", value)}
          />

          <div className="grid gap-3 sm:grid-cols-2">
            <Suggest
              label={t("field.toolSystem")}
              value={step.tool_system ?? ""}
              disabled={disabled}
              onChange={(value) => set("tool_system", value)}
            />
            <Suggest
              label={t("field.approval")}
              value={step.approval ?? ""}
              options={approvals}
              disabled={disabled}
              onChange={(value) => set("approval", value)}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Suggest
              label={t("field.output")}
              value={step.output ?? ""}
              disabled={disabled}
              onChange={(value) => set("output", value)}
            />
            <Suggest
              label={t("field.outputDestination")}
              value={step.output_destination ?? ""}
              disabled={disabled}
              onChange={(value) => set("output_destination", value)}
            />
          </div>

          {/*  Given its own block, and coloured, because it is the column the whole form turns
              on and the one a reviewer reads first. */}
          <div className="rounded-md border border-approval bg-approval-soft p-3">
            <Suggest
              label={t("field.mustNeverDo")}
              value={step.must_never_do ?? ""}
              multiline
              disabled={disabled}
              onChange={(value) => set("must_never_do", value)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------- section B: six situations

export function Situations({
  rules,
  situations,
  disabled,
  onChange,
}: {
  rules: EscalationRuleInput[];
  /** The six from the backend, each with the sheet's own label. */
  situations: { value: Situation; label: string }[];
  disabled: boolean;
  onChange: (next: EscalationRuleInput[]) => void;
}) {
  const t = useTranslations("agent");
  const byValue = new Map(rules.map((rule) => [rule.situation, rule]));

  const set = (situation: Situation, patch: Partial<EscalationRuleInput>) => {
    const existing = byValue.get(situation);
    const next: EscalationRuleInput = {
      situation,
      required_action: existing?.required_action ?? "",
      ...(existing?.escalate_to_label ? { escalate_to_label: existing.escalate_to_label } : {}),
      ...patch,
    };
    const others = rules.filter((rule) => rule.situation !== situation);
    //  An empty answer removes the row rather than storing a blank one — the schema requires a
    //  non-empty action, and a blank saved row would fail at the database instead of here.
    onChange(next.required_action.trim() ? [...others, next] : others);
  };

  const answered = rules.filter((rule) => rule.required_action.trim()).length;

  return (
    <div className="space-y-3">
      <Alert tone={answered === situations.length ? "success" : "info"}>
        {t("situationsProgress", { answered, total: situations.length })}
      </Alert>

      <ul className="space-y-3">
        {situations.map((situation) => {
          const rule = byValue.get(situation.value);
          const done = Boolean(rule?.required_action?.trim());
          return (
            <li
              key={situation.value}
              className={cn(
                "rounded-lg border bg-card p-3",
                done ? "border-border" : "border-dashed border-border",
              )}
            >
              <div className="mb-2 flex items-center gap-2">
                <p className="text-sm font-medium">{situation.label}</p>
                {done ? <Badge tone="success">{t("answered")}</Badge> : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
                <Suggest
                  label={t("field.requiredAction")}
                  value={rule?.required_action ?? ""}
                  multiline
                  disabled={disabled}
                  onChange={(value) => set(situation.value, { required_action: value })}
                />
                <Suggest
                  label={t("field.escalateTo")}
                  value={rule?.escalate_to_label ?? ""}
                  disabled={disabled || !done}
                  onChange={(value) =>
                    set(situation.value, { escalate_to_label: value || null })
                  }
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------- group 7: tools and scopes

export function Tools({
  tools,
  saved,
  permissions,
  disabled,
  mayGrant,
  onChange,
  onGrant,
  granting,
}: {
  tools: ToolInput[];
  /** What the server currently holds, so the grant state comes from it and never from a guess. */
  saved: ToolRead[];
  permissions: string[];
  disabled: boolean;
  mayGrant: boolean;
  onChange: (next: ToolInput[]) => void;
  onGrant: (toolId: string, granted: boolean) => void;
  granting: string | null;
}) {
  const t = useTranslations("agent");
  const byTool = new Map(saved.map((row) => [row.tool, row]));

  const set = (index: number, next: ToolInput) =>
    onChange(tools.map((tool, at) => (at === index ? next : tool)));

  const add = () =>
    onChange([...tools, { position: tools.length + 1, tool: "", scopes: [] }]);

  const remove = (index: number) =>
    onChange(
      tools
        .filter((_, at) => at !== index)
        .map((tool, at) => ({ ...tool, position: at + 1 })),
    );

  return (
    <div className="space-y-3">
      <Alert tone="info">{t("toolsIntro")}</Alert>

      {tools.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {t("noTools")}
        </p>
      ) : (
        <ul className="space-y-3">
          {tools.map((tool, index) => {
            const stored = byTool.get(tool.tool);
            //  A grant belongs to the scopes it was given for. Showing "granted" beside a
            //  changed scope set would claim access nobody has reviewed.
            const sameScopes =
              stored !== undefined &&
              JSON.stringify(stored.scopes ?? []) === JSON.stringify(tool.scopes);
            const granted = Boolean(stored?.granted) && sameScopes;

            return (
              <li key={index} className="rounded-lg border border-border bg-card p-3">
                <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
                  <div className="space-y-3">
                    <Suggest
                      label={t("field.tool")}
                      value={tool.tool}
                      disabled={disabled}
                      onChange={(value) => set(index, { ...tool, tool: value })}
                    />
                    <ScopePicker
                      scopes={tool.scopes}
                      permissions={permissions}
                      disabled={disabled}
                      onChange={(scopes) => set(index, { ...tool, scopes })}
                    />
                    <Suggest
                      label={t("field.toolPurpose")}
                      value={tool.purpose ?? ""}
                      disabled={disabled}
                      onChange={(value) => set(index, { ...tool, purpose: value || null })}
                    />
                  </div>

                  <div className="flex flex-col items-start gap-2 sm:w-44">
                    {granted ? (
                      <Badge tone="success" icon={<ShieldCheck className="size-3" />}>
                        {t("granted")}
                      </Badge>
                    ) : (
                      <Badge tone="approval" icon={<Lock className="size-3" />}>
                        {t("suggestionOnly")}
                      </Badge>
                    )}

                    {/*  The control is shown only when it would work. A disabled button with a
                        reason beats one that toasts a success nobody was granted. */}
                    {stored === undefined ? (
                      <p className="text-xs text-muted-foreground">{t("saveBeforeGrant")}</p>
                    ) : !mayGrant ? (
                      <p className="text-xs text-muted-foreground">{t("cannotGrant")}</p>
                    ) : !sameScopes ? (
                      <p className="text-xs text-muted-foreground">{t("scopesChanged")}</p>
                    ) : (
                      <Button
                        variant={granted ? "ghost" : "secondary"}
                        size="sm"
                        icon={<KeyRound className="size-3.5" />}
                        busy={granting === stored.id}
                        onClick={() => onGrant(stored.id, !granted)}
                      >
                        {granted ? t("withdraw") : t("grant")}
                      </Button>
                    )}

                    {granted && stored?.granted_at ? (
                      <p className="text-xs text-muted-foreground">
                        {t("grantedBy", {
                          when: new Date(stored.granted_at).toLocaleDateString(),
                        })}
                      </p>
                    ) : null}

                    {!disabled ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Trash2 className="size-3.5" />}
                        onClick={() => remove(index)}
                      >
                        {t("removeTool")}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {!disabled ? (
        <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={add}>
          {t("addTool")}
        </Button>
      ) : null}
    </div>
  );
}

function ScopePicker({
  scopes,
  permissions,
  disabled,
  onChange,
}: {
  scopes: string[];
  permissions: string[];
  disabled: boolean;
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations("agent");

  return (
    <fieldset disabled={disabled}>
      <legend className="mb-1 text-xs font-medium text-muted-foreground">
        {t("field.scopes")}
      </legend>
      <div className="flex flex-wrap gap-1.5">
        {permissions.map((permission) => {
          const on = scopes.includes(permission);
          return (
            <button
              key={permission}
              type="button"
              aria-pressed={on}
              disabled={disabled}
              onClick={() =>
                onChange(
                  on
                    ? scopes.filter((scope) => scope !== permission)
                    : [...scopes, permission],
                )
              }
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors duration-150",
                "motion-reduce:transition-none disabled:opacity-60",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                on
                  ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-accent",
              )}
            >
              {permission}
            </button>
          );
        })}
      </div>
      {scopes.length === 0 ? (
        <p className="mt-1 text-xs text-approval">{t("scopeRequired")}</p>
      ) : null}
    </fieldset>
  );
}

// ------------------------------------------------------------------- group 4: I/O schemas

export function IoSchemas({
  rows,
  inputTypes,
  outputFormats,
  disabled,
  onChange,
}: {
  rows: IoSchemaInput[];
  inputTypes: string[];
  outputFormats: string[];
  disabled: boolean;
  onChange: (next: IoSchemaInput[]) => void;
}) {
  const t = useTranslations("agent");

  const add = (direction: "input" | "output") => {
    const same = rows.filter((row) => row.direction === direction);
    onChange([
      ...rows,
      { position: same.length + 1, direction, name: "", required: true },
    ]);
  };

  const set = (index: number, next: IoSchemaInput) =>
    onChange(rows.map((row, at) => (at === index ? next : row)));

  const remove = (index: number) => onChange(rows.filter((_, at) => at !== index));

  return (
    <div className="space-y-4">
      {(["input", "output"] as const).map((direction) => (
        <section key={direction} className="space-y-2">
          <h3 className="text-sm font-medium">{t(`io.${direction}`)}</h3>
          <ul className="space-y-2">
            {rows.map((row, index) =>
              row.direction === direction ? (
                <li
                  key={index}
                  className="grid gap-3 rounded-lg border border-border bg-card p-3 sm:grid-cols-[2fr_1fr_auto]"
                >
                  <Suggest
                    label={t("field.ioName")}
                    value={row.name}
                    disabled={disabled}
                    onChange={(value) => set(index, { ...row, name: value })}
                  />
                  <Suggest
                    label={t("field.ioFormat")}
                    value={row.format ?? ""}
                    options={direction === "input" ? inputTypes : outputFormats}
                    disabled={disabled}
                    onChange={(value) => set(index, { ...row, format: value || null })}
                  />
                  {!disabled ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="self-end"
                      icon={<Trash2 className="size-3.5" />}
                      onClick={() => remove(index)}
                    >
                      <span className="sr-only">{t("removeIo")}</span>
                    </Button>
                  ) : null}
                </li>
              ) : null,
            )}
          </ul>
          {!disabled ? (
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus className="size-3.5" />}
              onClick={() => add(direction)}
            >
              {t(`io.add.${direction}`)}
            </Button>
          ) : null}
        </section>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------- group 6: knowledge

export function KnowledgeSources({
  rows,
  locations,
  disabled,
  onChange,
}: {
  rows: KnowledgeSourceInput[];
  locations: string[];
  disabled: boolean;
  onChange: (next: KnowledgeSourceInput[]) => void;
}) {
  const t = useTranslations("agent");

  const set = (index: number, next: KnowledgeSourceInput) =>
    onChange(rows.map((row, at) => (at === index ? next : row)));

  const add = () =>
    onChange([
      ...rows,
      { position: rows.length + 1, name: "", contains_personal_data: false },
    ]);

  const remove = (index: number) =>
    onChange(
      rows
        .filter((_, at) => at !== index)
        .map((row, at) => ({ ...row, position: at + 1 })),
    );

  return (
    <div className="space-y-3">
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {t("noKnowledge")}
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((row, index) => (
            <li key={index} className="space-y-3 rounded-lg border border-border bg-card p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Suggest
                  label={t("field.sourceName")}
                  value={row.name}
                  disabled={disabled}
                  onChange={(value) => set(index, { ...row, name: value })}
                />
                <Suggest
                  label={t("field.sourceLocation")}
                  value={row.location ?? ""}
                  options={locations}
                  disabled={disabled}
                  onChange={(value) => set(index, { ...row, location: value || null })}
                />
              </div>

              <div className="flex flex-wrap items-end gap-4">
                <Field label={t("field.retentionDays")} hint={t("retentionHint")}>
                  {(field) => (
                    <Input
                      {...field}
                      type="number"
                      min={1}
                      value={row.retention_days ?? ""}
                      disabled={disabled}
                      className="w-32"
                      onChange={(event) =>
                        set(index, {
                          ...row,
                          retention_days: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                    />
                  )}
                </Field>

                <label className="flex items-center gap-2 pb-2 text-sm">
                  <input
                    type="checkbox"
                    checked={row.contains_personal_data ?? false}
                    disabled={disabled}
                    onChange={(event) =>
                      set(index, { ...row, contains_personal_data: event.target.checked })
                    }
                    className="size-4 rounded border-border"
                  />
                  {t("containsPersonalData")}
                </label>

                {!disabled ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    icon={<Trash2 className="size-3.5" />}
                    onClick={() => remove(index)}
                  >
                    {t("removeSource")}
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      {!disabled ? (
        <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={add}>
          {t("addSource")}
        </Button>
      ) : null}
    </div>
  );
}
