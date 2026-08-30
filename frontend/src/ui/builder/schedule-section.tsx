"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { ScheduleWrite } from "@/lib/api/contract";
import {
  fetchSchedule,
  previewSchedule,
  removeSchedule,
  saveSchedule,
} from "@/lib/api/jobs";
import { cn } from "@/lib/cn";
import { contextFor, formatDateTimeWithZone } from "@/lib/format";
import { Alert } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { QueryStates } from "@/ui/states";

/**
 * A job's schedule, and what it would actually do — PLAN §8.
 *
 * The preview is the reason this screen is worth building rather than a form of settings.
 * Nobody can read *every 2 weeks, Tuesday and Thursday, shift* and know when it fires; ten
 * instants can be checked at a glance. They come from the server, computed by the same function
 * the runtime will use, so what somebody approves is what happens.
 *
 * **Every instant is shown with its zone.** `formatDateTimeWithZone` exists for exactly this: a
 * schedule's whole point is a time in a particular place, and a bare "09:00" on a screen read in
 * another country is a wrong answer that looks right.
 */
export function ScheduleSection({
  jobId,
  editable,
  timeZone,
}: {
  jobId: string;
  editable: boolean;
  timeZone: string | undefined;
}) {
  const t = useTranslations("schedule");
  const queryClient = useQueryClient();
  const format = contextFor(timeZone);
  //  Which date the preview starts from. Empty means now; a date lets somebody look at the week
  //  the clocks change without waiting for it.
  const [previewFrom, setPreviewFrom] = useState("");

  const schedule = useQuery({
    queryKey: ["job", jobId, "schedule"],
    queryFn: ({ signal }) => fetchSchedule(jobId, signal),
  });

  const preview = useQuery({
    queryKey: ["job", jobId, "schedule", "preview", previewFrom],
    queryFn: ({ signal }) =>
      previewSchedule(jobId, {
        count: 8,
        ...(previewFrom ? { from: `${previewFrom}T00:00:00Z` } : {}),
        signal,
      }),
    //  Only once a schedule exists. Asking for a preview of nothing is a 404 the screen would
    //  have to explain away.
    enabled: Boolean(schedule.data),
  });

  function reload() {
    void queryClient.invalidateQueries({ queryKey: ["job", jobId, "schedule"] });
  }

  const save = useMutation({
    mutationFn: (body: ScheduleWrite) => saveSchedule(jobId, body),
    onSuccess: reload,
  });
  const drop = useMutation({
    mutationFn: () => removeSchedule(jobId),
    onSuccess: reload,
  });

  const current = schedule.data;

  return (
    <div className="space-y-4">
      <QueryStates
        isPending={schedule.isPending}
        error={schedule.error}
        onRetry={() => void schedule.refetch()}
      >
        {current === null || current === undefined ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center">
            <CalendarClock aria-hidden className="mx-auto size-7 text-muted-foreground" />
            <p className="mt-3 text-sm font-medium">{t("noneTitle")}</p>
            <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
              {t("noneBody")}
            </p>
            {editable ? (
              <Button
                variant="primary"
                className="mt-4"
                busy={save.isPending}
                onClick={() =>
                  save.mutate({
                    auto_run: false,
                    //  Defaults to the reader's own zone. Better than picking UTC, which is
                    //  nobody's working day, and better than guessing from the browser.
                    timezone: timeZone ?? "UTC",
                    frequency: "daily",
                    at_time: "09:00:00",
                    interval: 1,
                    weekdays: [],
                    monthday: null,
                    dst_policy: "shift",
                    ambiguous_policy: "first",
                    skip_dates: [],
                    weekdays_only: false,
                    overlap_policy: "skip",
                    missed_run_policy: "skip",
                    max_concurrent: 1,
                    pinned_version_id: null,
                    requires_approval_per_run: false,
                    expected_version: null,
                  })
                }
              >
                {t("addSchedule")}
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            <Editor
              schedule={current}
              disabled={!editable}
              busy={save.isPending}
              onSave={(body) => save.mutate(body)}
            />

            {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}

            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <p className="text-sm font-semibold">{t("previewTitle")}</p>
                <div className="w-44">
                  <Field label={t("previewFrom")} htmlFor="preview-from">
                    {(field) => (
                      <Input
                        {...field}
                        type="date"
                        value={previewFrom}
                        onChange={(event) => setPreviewFrom(event.target.value)}
                      />
                    )}
                  </Field>
                </div>
              </div>

              <QueryStates
                isPending={preview.isPending}
                error={preview.error}
                onRetry={() => void preview.refetch()}
              >
                {preview.data ? (
                  <>
                    {preview.data.occurrences.length === 0 ? (
                      <Alert tone="warning">{t("neverFires")}</Alert>
                    ) : (
                      <ol className="space-y-1">
                        {preview.data.occurrences.map((moment) => (
                          <li
                            key={moment}
                            className="flex items-baseline gap-2 text-sm tabular-nums"
                          >
                            <span
                              aria-hidden
                              className="size-1.5 shrink-0 rounded-full bg-primary"
                            />
                            {/*  Always with the zone. A bare "09:00" read in another country is
                                a wrong answer that looks right. */}
                            {formatDateTimeWithZone(moment, {
                              ...format,
                              timeZone: preview.data.timezone,
                            })}
                          </li>
                        ))}
                      </ol>
                    )}

                    {(preview.data.notes ?? []).length > 0 ? (
                      <Alert tone="info" className="mt-3" title={t("worthKnowing")}>
                        <ul className="mt-1 space-y-1">
                          {(preview.data.notes ?? []).map((note) => (
                            <li key={note}>{note}</li>
                          ))}
                        </ul>
                      </Alert>
                    ) : null}
                  </>
                ) : null}
              </QueryStates>
            </div>

            {editable ? (
              <Button
                variant="ghost"
                className="text-muted-foreground hover:text-danger"
                icon={<Trash2 className="size-4" />}
                busy={drop.isPending}
                onClick={() => drop.mutate()}
              >
                {t("removeSchedule")}
              </Button>
            ) : null}
          </>
        )}
      </QueryStates>
    </div>
  );
}

const FREQUENCIES = ["hourly", "daily", "weekly", "monthly"] as const;
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

function Editor({
  schedule,
  disabled,
  busy,
  onSave,
}: {
  schedule: NonNullable<Awaited<ReturnType<typeof fetchSchedule>>>;
  disabled: boolean;
  busy: boolean;
  onSave: (body: ScheduleWrite) => void;
}) {
  const t = useTranslations("schedule");
  const [draft, setDraft] = useState<ScheduleWrite>({
    auto_run: schedule.auto_run,
    timezone: schedule.timezone,
    frequency: schedule.frequency,
    interval: schedule.interval ?? 1,
    at_time: schedule.at_time,
    weekdays: schedule.weekdays ?? [],
    monthday: schedule.monthday ?? null,
    dst_policy: schedule.dst_policy ?? "shift",
    ambiguous_policy: schedule.ambiguous_policy ?? "first",
    skip_dates: schedule.skip_dates ?? [],
    weekdays_only: schedule.weekdays_only ?? false,
    overlap_policy: schedule.overlap_policy ?? "skip",
    missed_run_policy: schedule.missed_run_policy ?? "skip",
    max_concurrent: schedule.max_concurrent ?? 1,
    pinned_version_id: schedule.pinned_version_id ?? null,
    requires_approval_per_run: schedule.requires_approval_per_run ?? false,
    expected_version: schedule.version,
  });

  const set = (patch: Partial<ScheduleWrite>) => setDraft({ ...draft, ...patch });

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      {/*  Auto-run first, and stated plainly. It is the only setting on this screen that decides
          whether anything happens at all. */}
      <label className="flex items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={draft.auto_run ?? false}
          disabled={disabled}
          onChange={(event) => set({ auto_run: event.target.checked })}
          className="mt-0.5 size-4 rounded border-border"
        />
        <span>
          <span className="font-medium">{t("autoRun")}</span>
          <span className="block text-muted-foreground">{t("autoRunHelp")}</span>
        </span>
      </label>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label className="mb-1.5 block text-sm font-medium">{t("frequency")}</label>
          <div className="flex flex-wrap gap-1.5">
            {FREQUENCIES.map((option) => (
              <button
                key={option}
                type="button"
                disabled={disabled}
                aria-pressed={draft.frequency === option}
                onClick={() => set({ frequency: option })}
                className={cn(
                  "rounded-md border px-2.5 py-1.5 text-sm transition-colors duration-150",
                  "motion-reduce:transition-none disabled:opacity-60",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                  draft.frequency === option
                    ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                    : "border-border bg-card hover:bg-accent",
                )}
              >
                {t(`frequencyValue.${option}`)}
              </button>
            ))}
          </div>
        </div>

        <Field label={t("interval")}>
          {(field) => (
            <Input
              {...field}
              type="number"
              min={1}
              max={999}
              value={draft.interval ?? 1}
              disabled={disabled}
              onChange={(event) => set({ interval: Number(event.target.value) || 1 })}
            />
          )}
        </Field>

        <Field label={t("atTime")}>
          {(field) => (
            <Input
              {...field}
              type="time"
              value={(draft.at_time ?? "09:00:00").slice(0, 5)}
              disabled={disabled}
              onChange={(event) => set({ at_time: `${event.target.value}:00` })}
            />
          )}
        </Field>
      </div>

      {draft.frequency === "weekly" ? (
        <div>
          <label className="mb-1.5 block text-sm font-medium">{t("onDays")}</label>
          <div className="flex flex-wrap gap-1.5">
            {WEEKDAYS.map((day) => {
              const on = (draft.weekdays ?? []).includes(day);
              return (
                <button
                  key={day}
                  type="button"
                  disabled={disabled}
                  aria-pressed={on}
                  onClick={() =>
                    set({
                      weekdays: on
                        ? (draft.weekdays ?? []).filter((value) => value !== day)
                        : [...(draft.weekdays ?? []), day],
                    })
                  }
                  className={cn(
                    "rounded-md border px-2.5 py-1.5 text-sm transition-colors duration-150",
                    "motion-reduce:transition-none disabled:opacity-60",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                    on
                      ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                      : "border-border bg-card hover:bg-accent",
                  )}
                >
                  {t(`weekday.${day}`)}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {draft.frequency === "monthly" ? (
        <Field label={t("monthday")} required>
          {(field) => (
            <Input
              {...field}
              type="number"
              min={1}
              max={31}
              value={draft.monthday ?? 1}
              disabled={disabled}
              onChange={(event) => set({ monthday: Number(event.target.value) || 1 })}
            />
          )}
        </Field>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("timezone")} required>
          {(field) => (
            <Input
              {...field}
              value={draft.timezone}
              disabled={disabled}
              placeholder="Asia/Kolkata"
              onChange={(event) => set({ timezone: event.target.value })}
            />
          )}
        </Field>
        <Field label={t("maxConcurrent")}>
          {(field) => (
            <Input
              {...field}
              type="number"
              min={1}
              max={100}
              value={draft.max_concurrent ?? 1}
              disabled={disabled}
              onChange={(event) => set({ max_concurrent: Number(event.target.value) || 1 })}
            />
          )}
        </Field>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.weekdays_only ?? false}
          disabled={disabled}
          onChange={(event) => set({ weekdays_only: event.target.checked })}
          className="size-4 rounded border-border"
        />
        {t("weekdaysOnly")}
      </label>

      {/*  The two clock-change questions. Grouped and explained, because they are the settings
          people get wrong and only notice twice a year. */}
      <fieldset disabled={disabled} className="rounded-md border border-border p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("clockChanges")}
        </legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <Choice
            label={t("dstPolicy")}
            help={t("dstHelp")}
            value={draft.dst_policy ?? "shift"}
            options={["shift", "skip"]}
            render={(value) => t(`dstValue.${value}`)}
            onChange={(value) => set({ dst_policy: value as ScheduleWrite["dst_policy"] })}
          />
          <Choice
            label={t("ambiguousPolicy")}
            help={t("ambiguousHelp")}
            value={draft.ambiguous_policy ?? "first"}
            options={["first", "both"]}
            render={(value) => t(`ambiguousValue.${value}`)}
            onChange={(value) =>
              set({ ambiguous_policy: value as ScheduleWrite["ambiguous_policy"] })
            }
          />
        </div>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <Choice
          label={t("overlapPolicy")}
          help={t("overlapHelp")}
          value={draft.overlap_policy ?? "skip"}
          options={["skip", "queue", "allow"]}
          render={(value) => t(`overlapValue.${value}`)}
          onChange={(value) =>
            set({ overlap_policy: value as ScheduleWrite["overlap_policy"] })
          }
        />
        <Choice
          label={t("missedRunPolicy")}
          help={t("missedHelp")}
          value={draft.missed_run_policy ?? "skip"}
          options={["skip", "run_once", "run_all"]}
          render={(value) => t(`missedValue.${value}`)}
          onChange={(value) =>
            set({ missed_run_policy: value as ScheduleWrite["missed_run_policy"] })
          }
        />
      </div>

      <label className="flex items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={draft.requires_approval_per_run ?? false}
          disabled={disabled}
          onChange={(event) => set({ requires_approval_per_run: event.target.checked })}
          className="mt-0.5 size-4 rounded border-border"
        />
        <span>
          <span className="font-medium">{t("approvalPerRun")}</span>
          <span className="block text-muted-foreground">{t("approvalPerRunHelp")}</span>
        </span>
      </label>

      <Button
        variant="primary"
        disabled={disabled}
        busy={busy}
        onClick={() => onSave({ ...draft, expected_version: schedule.version })}
      >
        {t("saveSchedule")}
      </Button>
    </div>
  );
}

function Choice({
  label,
  help,
  value,
  options,
  render,
  onChange,
}: {
  label: string;
  help: string;
  value: string;
  options: string[];
  render: (value: string) => string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <p className="mb-1 text-sm font-medium">{label}</p>
      <p className="mb-1.5 text-xs text-muted-foreground">{help}</p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={value === option}
            onClick={() => onChange(option)}
            className={cn(
              "rounded-md border px-2.5 py-1.5 text-sm transition-colors duration-150",
              "motion-reduce:transition-none disabled:opacity-60",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              value === option
                ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-accent",
            )}
          >
            {render(option)}
          </button>
        ))}
      </div>
    </div>
  );
}
