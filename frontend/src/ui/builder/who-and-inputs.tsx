"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import type {
  AiAccess,
  AssignmentRuleInput,
  InputRequirement,
  JobInputDefinition,
  JobToolDefinition,
  WhoType,
} from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Suggest } from "@/ui/builder/suggest";

/**
 * PLAN §8's *"multiple WHO assignment rules"* and *"typed INPUT definitions"*.
 *
 * Both are lists rather than fields, and both for the same reason: a single value works until the
 * organisation is real. One WHO breaks the first time somebody leaves; one untyped input cannot
 * say whether a model is allowed to read it.
 */

const WHO_TYPES: WhoType[] = [
  "user",
  "team",
  "department",
  "role",
  "hierarchy_position",
  "hierarchy_subtree",
  "dynamic_group",
];

export function WhoRules({
  rules,
  disabled,
  onChange,
}: {
  rules: AssignmentRuleInput[];
  disabled: boolean;
  onChange: (next: AssignmentRuleInput[]) => void;
}) {
  const t = useTranslations("job");

  return (
    <div className="space-y-3">
      {rules.length === 0 ? (
        <Alert tone="warning">{t("noWhoRules")}</Alert>
      ) : (
        <ul className="space-y-2">
          {rules.map((rule, index) => (
            <li key={index} className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-start gap-3">
                <span
                  aria-hidden
                  className="mt-1 grid size-6 shrink-0 place-items-center rounded-md bg-human-soft text-xs font-semibold text-human"
                >
                  {index + 1}
                </span>

                <div className="min-w-0 flex-1 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        {t("whoType")}
                      </label>
                      <select
                        value={rule.who_type}
                        disabled={disabled}
                        onChange={(event) =>
                          onChange(
                            rules.map((item, at) =>
                              at === index
                                ? { ...item, who_type: event.target.value as WhoType }
                                : item,
                            ),
                          )
                        }
                        className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm disabled:opacity-60"
                      >
                        {WHO_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {t(`whoTypeValue.${type}`)}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/*  A label rather than a picker: the pickers for a team, a role and a
                        hierarchy position are three different endpoints that arrive with the
                        screens that own them. Until then this holds what somebody typed, which
                        the server accepts and the runtime will resolve. */}
                    <Suggest
                      label={t("whoTarget")}
                      value={rule.target_label ?? ""}
                      disabled={disabled}
                      placeholder={t("whoTargetPlaceholder")}
                      onChange={(value) =>
                        onChange(
                          rules.map((item, at) =>
                            at === index ? { ...item, target_label: value || null } : item,
                          ),
                        )
                      }
                    />
                  </div>

                  <Suggest
                    label={t("whoCondition")}
                    value={rule.condition_note ?? ""}
                    disabled={disabled}
                    placeholder={t("whoConditionPlaceholder")}
                    onChange={(value) =>
                      onChange(
                        rules.map((item, at) =>
                          at === index ? { ...item, condition_note: value || null } : item,
                        ),
                      )
                    }
                  />

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={rule.all_must_act ?? false}
                      disabled={disabled}
                      onChange={(event) =>
                        onChange(
                          rules.map((item, at) =>
                            at === index
                              ? { ...item, all_must_act: event.target.checked }
                              : item,
                          ),
                        )
                      }
                      className="size-4 rounded border-border"
                    />
                    {t("allMustAct")}
                  </label>
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  className="size-8 shrink-0 px-0 text-muted-foreground hover:text-danger"
                  aria-label={t("removeRule", { rule: index + 1 })}
                  disabled={disabled}
                  onClick={() => onChange(rules.filter((_, at) => at !== index))}
                  icon={<Trash2 className="size-3.5" />}
                />
              </div>
            </li>
          ))}
        </ul>
      )}

      <Button
        icon={<Plus className="size-4" />}
        disabled={disabled}
        onClick={() =>
          onChange([...rules, { who_type: "role", target_label: null, all_must_act: false }])
        }
      >
        {t("addWhoRule")}
      </Button>
    </div>
  );
}

const REQUIREMENTS: InputRequirement[] = ["Mandatory", "Optional", "Conditional"];
const AI_ACCESS: AiAccess[] = ["none", "read", "read_write"];
const CLASSIFICATIONS = ["internal", "confidential", "personal_data", "public"] as const;

export function JobInputs({
  inputs,
  inputTypes,
  disabled,
  onChange,
}: {
  inputs: JobInputDefinition[];
  inputTypes: string[];
  disabled: boolean;
  onChange: (next: JobInputDefinition[]) => void;
}) {
  const t = useTranslations("job");

  function edit(index: number, patch: Partial<JobInputDefinition>) {
    onChange(inputs.map((item, at) => (at === index ? { ...item, ...patch } : item)));
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {inputs.map((item, index) => {
          //  The combination the schema refuses. Shown here so somebody sees why the save will
          //  fail before it does, rather than reading a constraint error afterwards.
          const refused =
            item.classification === "personal_data" && item.ai_access === "read_write";
          const conditionalWithoutCondition =
            item.requirement === "Conditional" && !(item.condition_note ?? "").trim();

          return (
            <li
              key={index}
              className={cn(
                "rounded-lg border bg-card p-3",
                refused || conditionalWithoutCondition
                  ? "border-danger"
                  : "border-border",
              )}
            >
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Suggest
                      label={t("inputName")}
                      value={item.name}
                      disabled={disabled}
                      onChange={(value) => edit(index, { name: value })}
                    />
                    <Suggest
                      label={t("inputType")}
                      value={item.input_type}
                      options={inputTypes}
                      disabled={disabled}
                      onChange={(value) => edit(index, { input_type: value })}
                    />
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <Suggest
                      label={t("inputSource")}
                      value={item.source ?? ""}
                      disabled={disabled}
                      onChange={(value) => edit(index, { source: value || null })}
                    />
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        {t("inputRequirement")}
                      </label>
                      <div className="flex flex-wrap gap-1.5">
                        {REQUIREMENTS.map((option) => (
                          <button
                            key={option}
                            type="button"
                            disabled={disabled}
                            aria-pressed={item.requirement === option}
                            onClick={() => edit(index, { requirement: option })}
                            className={cn(
                              "rounded-md border px-2 py-1 text-xs transition-colors duration-150",
                              "motion-reduce:transition-none disabled:opacity-60",
                              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                              item.requirement === option
                                ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                                : "border-border bg-card hover:bg-accent",
                            )}
                          >
                            {t(`requirementValue.${option}`)}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  {item.requirement === "Conditional" ? (
                    <Suggest
                      label={t("inputCondition")}
                      value={item.condition_note ?? ""}
                      disabled={disabled}
                      placeholder={t("inputConditionPlaceholder")}
                      onChange={(value) => edit(index, { condition_note: value || null })}
                    />
                  ) : null}

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        {t("classification")}
                      </label>
                      <select
                        value={item.classification ?? "internal"}
                        disabled={disabled}
                        onChange={(event) =>
                          edit(index, { classification: event.target.value })
                        }
                        className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm disabled:opacity-60"
                      >
                        {CLASSIFICATIONS.map((option) => (
                          <option key={option} value={option}>
                            {t(`classificationValue.${option}`)}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        {t("aiAccess")}
                      </label>
                      <div className="flex flex-wrap gap-1.5">
                        {AI_ACCESS.map((option) => (
                          <button
                            key={option}
                            type="button"
                            disabled={disabled}
                            aria-pressed={item.ai_access === option}
                            onClick={() => edit(index, { ai_access: option })}
                            className={cn(
                              "rounded-md border px-2 py-1 text-xs transition-colors duration-150",
                              "motion-reduce:transition-none disabled:opacity-60",
                              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                              item.ai_access === option
                                ? "border-[var(--ub-brand)] bg-ai-soft text-ai"
                                : "border-border bg-card hover:bg-accent",
                            )}
                          >
                            {t(`aiAccessValue.${option}`)}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  {refused ? (
                    <Alert tone="danger">{t("personalDataNoWrite")}</Alert>
                  ) : null}
                  {conditionalWithoutCondition ? (
                    <Alert tone="danger">{t("conditionalNeedsCondition")}</Alert>
                  ) : null}
                  {item.ai_access !== "none" ? (
                    <Badge tone="ai">{t("agentCanRead")}</Badge>
                  ) : null}
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  className="size-8 shrink-0 px-0 text-muted-foreground hover:text-danger"
                  aria-label={t("removeInput", { input: index + 1 })}
                  disabled={disabled}
                  onClick={() => onChange(inputs.filter((_, at) => at !== index))}
                  icon={<Trash2 className="size-3.5" />}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <Button
        icon={<Plus className="size-4" />}
        disabled={disabled}
        onClick={() =>
          onChange([
            ...inputs,
            {
              name: "",
              input_type: inputTypes[0] ?? "Text / Form",
              requirement: "Optional",
              classification: "internal",
              //  `none` by default, matching the server. The safe answer should be the one
              //  somebody chooses, not the one that happens when they do not.
              ai_access: "none",
            },
          ])
        }
      >
        {t("addInput")}
      </Button>
    </div>
  );
}


/**
 * The systems this job touches, and what it may do with each — PLAN §8 group 7.
 *
 * **A permission, not a note.** PLAN §19 requires every external action to go through a governed
 * gateway, and this is the ceiling that gateway checks: a job that never declared `Send` on
 * Outlook does not get to send mail, whatever a model decides mid-run. So permissions are chosen
 * rather than typed, and a tool with none is refused.
 *
 * Naming a tool is not connecting one. Nothing here connects to anything until Gate 8 wires the
 * real integrations — but saying what a job needs is useful long before that, and the row becomes
 * a real connection without moving.
 */
export function JobTools({
  tools,
  permissions,
  stepCount,
  disabled,
  onChange,
}: {
  tools: JobToolDefinition[];
  permissions: string[];
  stepCount: number;
  disabled: boolean;
  onChange: (next: JobToolDefinition[]) => void;
}) {
  const t = useTranslations("job");

  function edit(index: number, patch: Partial<JobToolDefinition>) {
    onChange(tools.map((item, at) => (at === index ? { ...item, ...patch } : item)));
  }

  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {tools.map((tool, index) => {
          const none = (tool.permissions ?? []).length === 0;
          return (
            <li
              key={index}
              className={cn(
                "rounded-lg border bg-card p-3",
                none ? "border-danger" : "border-border",
              )}
            >
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Suggest
                      label={t("toolName")}
                      value={tool.name}
                      disabled={disabled}
                      placeholder={t("toolNamePlaceholder")}
                      onChange={(value) => edit(index, { name: value })}
                    />
                    <div>
                      <label className="mb-1 block text-xs font-medium text-muted-foreground">
                        {t("toolStep")}
                      </label>
                      <select
                        value={tool.step_position ?? ""}
                        disabled={disabled}
                        onChange={(event) =>
                          edit(index, {
                            step_position: event.target.value
                              ? Number(event.target.value)
                              : null,
                          })
                        }
                        className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm disabled:opacity-60"
                      >
                        <option value="">{t("toolWholeJob")}</option>
                        {Array.from({ length: stepCount }, (_, i) => i + 1).map((n) => (
                          <option key={n} value={n}>
                            {t("toolStepNumber", { step: n })}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">
                      {t("toolPermissions")}
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {permissions.map((option) => {
                        const on = (tool.permissions ?? []).includes(option);
                        return (
                          <button
                            key={option}
                            type="button"
                            disabled={disabled}
                            aria-pressed={on}
                            onClick={() =>
                              edit(index, {
                                permissions: on
                                  ? (tool.permissions ?? []).filter((p) => p !== option)
                                  : [...(tool.permissions ?? []), option],
                              })
                            }
                            className={cn(
                              "rounded-md border px-2 py-1 text-xs transition-colors duration-150",
                              "motion-reduce:transition-none disabled:opacity-60",
                              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                              on
                                ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                                : "border-border bg-card hover:bg-accent",
                            )}
                          >
                            {option}
                          </button>
                        );
                      })}
                    </div>
                    {none ? (
                      <Alert tone="danger" className="mt-2">
                        {t("toolNeedsPermission")}
                      </Alert>
                    ) : null}
                  </div>

                  <Suggest
                    label={t("toolNote")}
                    value={tool.note ?? ""}
                    disabled={disabled}
                    onChange={(value) => edit(index, { note: value || null })}
                  />
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  className="size-8 shrink-0 px-0 text-muted-foreground hover:text-danger"
                  aria-label={t("removeTool", { tool: index + 1 })}
                  disabled={disabled}
                  onClick={() => onChange(tools.filter((_, at) => at !== index))}
                  icon={<Trash2 className="size-3.5" />}
                />
              </div>
            </li>
          );
        })}
      </ul>

      <Button
        icon={<Plus className="size-4" />}
        disabled={disabled}
        onClick={() =>
          onChange([...tools, { name: "", permissions: ["Read"], step_position: null }])
        }
      >
        {t("addTool")}
      </Button>
    </div>
  );
}
