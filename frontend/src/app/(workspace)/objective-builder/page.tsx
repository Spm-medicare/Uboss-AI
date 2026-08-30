"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, Target } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { ObjectiveCard as Card_ } from "@/lib/api/contract";
import { can } from "@/lib/api/auth";
import { createObjective, fetchObjectives } from "@/lib/api/objectives";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { contextFor, formatDate } from "@/lib/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Field,
  Input,
  QueryStates,
} from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * The Objective cards — PLAN §7's list.
 *
 * §7 is explicit that this and the Builder are one module: *"This single module contains all
 * Objective cards, creation, analysis, publishing and progress. There is no duplicate Objective
 * page."* So this screen lists and creates, and opening a card goes to the Builder. There is no
 * third page showing the same objective in a different shape.
 *
 * Every figure is real. `step_count` is a count of rows somebody typed; there is no completion
 * percentage, because a percentage needs a definition of "complete" and inventing one would put
 * a number on screen that means nothing.
 */
export default function ObjectivesPage() {
  const t = useTranslations("objective");
  const { user } = useSession();
  const router = useRouter();
  const [filter, setFilter] = useState<string>("");

  const objectives = useQuery({
    queryKey: ["objectives", filter],
    queryFn: ({ signal }) =>
      fetchObjectives(filter ? { status: filter, signal } : { signal }),
  });

  const mayCreate = can(user, "edit_draft");

  return (
    <AppShell
      title={t("objectives")}
      action={mayCreate ? <NewObjective onCreated={(id) => router.push(`/objective-builder/${id}`)} /> : undefined}
    >
      <div className="mx-auto max-w-5xl space-y-5">
        <QueryStates
          isPending={objectives.isPending}
          error={objectives.error}
          onRetry={() => void objectives.refetch()}
        >
          {objectives.data?.is_empty ? (
            <Card>
              <CardBody className="space-y-3 py-12 text-center">
                <Target aria-hidden className="mx-auto size-8 text-muted-foreground" />
                <p className="text-sm font-medium">{t("emptyTitle")}</p>
                <p className="mx-auto max-w-sm text-sm text-muted-foreground">
                  {mayCreate ? t("emptyBody") : t("emptyBodyReadOnly")}
                </p>
              </CardBody>
            </Card>
          ) : (
            <>
              <Filters
                current={filter}
                onChange={setFilter}
                counts={objectives.data?.objectives ?? []}
              />

              {objectives.data && objectives.data.objectives.length === 0 ? (
                //  Not `is_empty` — there are objectives, just none matching. Different words,
                //  and an offer to clear the filter rather than to create the first one.
                <Alert tone="info">
                  {t("noneMatching")}{" "}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => setFilter("")}
                  >
                    {t("clearFilter")}
                  </button>
                </Alert>
              ) : (
                <ul className="grid gap-3 sm:grid-cols-2">
                  {(objectives.data?.objectives ?? []).map((card) => (
                    <ObjectiveTile key={card.id} card={card} timeZone={user?.timezone} />
                  ))}
                </ul>
              )}
            </>
          )}
        </QueryStates>
      </div>
    </AppShell>
  );
}

/** The statuses PLAN §7 names, as filters. Only those that exist in the data are offered. */
function Filters({
  current,
  onChange,
  counts,
}: {
  current: string;
  onChange: (value: string) => void;
  counts: Card_[];
}) {
  const t = useTranslations("objective");
  const present = Array.from(new Set(counts.map((card) => card.status)));
  const options = ["", ...present];

  if (present.length < 2) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => (
        <button
          key={option || "all"}
          type="button"
          aria-pressed={current === option}
          onClick={() => onChange(option)}
          className={cn(
            "rounded-full border px-3 py-1 text-sm transition-colors duration-150",
            "motion-reduce:transition-none",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
            current === option
              ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
              : "border-border bg-card hover:bg-accent",
          )}
        >
          {option ? t(`status.${option}`) : t("allStatuses")}
        </button>
      ))}
    </div>
  );
}

function ObjectiveTile({
  card,
  timeZone,
}: {
  card: Card_;
  timeZone: string | undefined;
}) {
  const t = useTranslations("objective");
  const format = contextFor(timeZone);
  const tones: Record<string, "neutral" | "human" | "ai" | "approval" | "success"> = {
    draft: "neutral",
    analyzing: "ai",
    needs_review: "approval",
    ready_to_publish: "human",
    published: "success",
    active: "success",
    paused: "approval",
    archived: "neutral",
  };

  return (
    <li>
      <Link
        href={`/objective-builder/${card.id}`}
        className={cn(
          "group flex h-full flex-col gap-3 rounded-lg border border-border bg-card p-4",
          "transition-colors duration-150 hover:border-[var(--ub-brand)] motion-reduce:transition-none",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <p className="min-w-0 flex-1 font-medium leading-snug">{card.title}</p>
          <Badge tone={tones[card.status] ?? "neutral"}>{t(`status.${card.status}`)}</Badge>
        </div>

        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {card.department ? (
            <div className="flex gap-1">
              <dt className="sr-only">{t("department")}</dt>
              <dd>{card.department}</dd>
            </div>
          ) : null}
          {card.owner_name ? (
            <div className="flex gap-1">
              <dt className="sr-only">{t("owner")}</dt>
              <dd>{card.owner_name}</dd>
            </div>
          ) : null}
          {card.target_date ? (
            <div className="flex gap-1">
              <dt>{t("due")}</dt>
              <dd>{formatDate(card.target_date, format)}</dd>
            </div>
          ) : null}
        </dl>

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-3 text-xs">
          {/*  A count of rows somebody actually typed. Never a percentage — that would need a
              definition of "complete" nobody has agreed. */}
          <span className="text-muted-foreground">
            {t("stepsRecorded", { count: card.step_count })}
          </span>
          <span className="flex items-center gap-1 text-primary opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none">
            {t("open")}
            <ArrowRight aria-hidden className="size-3.5" />
          </span>
        </div>
      </Link>
    </li>
  );
}

/** Start a draft from a title. Everything else is filled in inside the Builder. */
function NewObjective({ onCreated }: { onCreated: (id: string) => void }) {
  const t = useTranslations("objective");
  const tCommon = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () => createObjective({ title: title.trim() }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["objectives"] });
      onCreated(result.id);
    },
  });

  if (!open) {
    return (
      <Button
        variant="primary"
        size="sm"
        icon={<Plus className="size-3.5" />}
        onClick={() => setOpen(true)}
      >
        {t("newObjective")}
      </Button>
    );
  }

  return (
    <form
      className="flex items-end gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate();
      }}
    >
      <Field label={t("objectiveName")} htmlFor="new-objective" required>
        {(field) => (
          <Input
            {...field}
            value={title}
            autoFocus
            placeholder={t("newObjectivePlaceholder")}
            onChange={(event) => setTitle(event.target.value)}
            className="h-8 w-64 text-sm"
          />
        )}
      </Field>
      <Button
        type="submit"
        variant="primary"
        size="sm"
        busy={create.isPending}
        disabled={!title.trim()}
      >
        {t("start")}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
        {tCommon("cancel")}
      </Button>
    </form>
  );
}
