"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  FileSpreadsheet,
  Sparkles,
  Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import type { ImportPreview, ImportSummary } from "@/lib/api/contract";
import {
  applyImport,
  fetchPreview,
  proposeMapping,
  setMapping,
  uploadImport,
} from "@/lib/api/hierarchy-import";
import { can } from "@/lib/api/auth";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/cn";
import { formatBytes, contextFor } from "@/lib/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DeniedState,
  QueryStates,
} from "@/ui";
import { AppShell } from "@/ui/shell/app-shell";

/**
 * Import a structure file — PLAN §5's seven steps, as four screens.
 *
 * The steps are separate on screen for the same reason they are separate routes: each one is a
 * place a person stops and looks. A single "import this file" button would be shorter and would
 * remove the review the whole design exists for.
 *
 * Two things this screen must never do, and both are easy to do by accident:
 *
 * **Never imply the model did more than it did.** It is asked about column headings that nothing
 * matched, and nothing else. Where no model was reachable the screen says so in those words —
 * an empty suggestion list looks identical to a model with no ideas, and they are different
 * facts.
 *
 * **Never show a tree that is not the one that would be applied.** The preview comes from the
 * server, built by the same code the apply uses. Nothing here derives a second version of it.
 */
type Stage = "choose" | "map" | "review" | "done";

export default function ImportPage() {
  const t = useTranslations("import");
  const { user } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [record, setRecord] = useState<ImportSummary | null>(null);
  const [stage, setStage] = useState<Stage>("choose");

  if (user && !can(user, "administer")) {
    return (
      <AppShell title={t("title")}>
        <DeniedState />
      </AppShell>
    );
  }

  return (
    <AppShell
      title={t("title")}
      breadcrumb={[{ label: t("hierarchy"), href: "/hierarchy" }]}
    >
      <div className="mx-auto max-w-4xl space-y-6">
        <Steps current={stage} />

        {stage === "choose" ? (
          <ChooseFile
            onUploaded={(summary) => {
              setRecord(summary);
              setStage("map");
            }}
          />
        ) : null}

        {stage === "map" && record ? (
          <MapColumns
            record={record}
            onChanged={setRecord}
            onConfirmed={(summary) => {
              setRecord(summary);
              setStage("review");
            }}
          />
        ) : null}

        {stage === "review" && record ? (
          <Review
            record={record}
            onBack={() => setStage("map")}
            onApplied={() => {
              void queryClient.invalidateQueries({ queryKey: ["hierarchy"] });
              setStage("done");
            }}
          />
        ) : null}

        {stage === "done" ? (
          <Card>
            <CardBody className="space-y-4 py-10 text-center">
              <Check aria-hidden className="mx-auto size-8 text-success" />
              <p className="text-sm font-medium">{t("doneTitle")}</p>
              <p className="mx-auto max-w-sm text-sm text-muted-foreground">
                {t("doneBody")}
              </p>
              <Button variant="primary" onClick={() => router.push("/hierarchy")}>
                {t("seeTheTree")}
              </Button>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}

/** Where the person is, and what is still ahead. Four labels, no invented progress bar. */
function Steps({ current }: { current: Stage }) {
  const t = useTranslations("import");
  const order: Stage[] = ["choose", "map", "review", "done"];
  const index = order.indexOf(current);

  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      {order.map((step, position) => (
        <li key={step} className="flex items-center gap-2">
          <span
            className={cn(
              "flex items-center gap-1.5",
              position === index && "font-medium",
              position > index && "text-muted-foreground",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "grid size-5 place-items-center rounded-full text-xs",
                position < index && "bg-success-soft text-success",
                position === index && "bg-primary text-primary-foreground",
                position > index && "bg-muted text-muted-foreground",
              )}
            >
              {position < index ? "✓" : position + 1}
            </span>
            {t(`steps.${step}`)}
          </span>
          {position < order.length - 1 ? (
            <span aria-hidden className="text-muted-foreground">
              →
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** Steps 1 and 2 — the file goes into quarantine and is read. Nothing is created. */
function ChooseFile({ onUploaded }: { onUploaded: (summary: ImportSummary) => void }) {
  const t = useTranslations("import");
  const { user } = useSession();
  const input = useRef<HTMLInputElement>(null);
  const [chosen, setChosen] = useState<File | null>(null);
  const format = contextFor(user?.timezone);

  const upload = useMutation({
    mutationFn: () => uploadImport(chosen!),
    onSuccess: onUploaded,
  });

  return (
    <Card>
      <CardHeader title={t("chooseTitle")} description={t("chooseBody")} />
      <CardBody className="space-y-4">
        <input
          ref={input}
          type="file"
          accept=".csv,.xlsx,.xlsm,.txt"
          className="sr-only"
          onChange={(event) => setChosen(event.target.files?.[0] ?? null)}
        />

        <div className="flex flex-wrap items-center gap-3">
          <Button
            icon={<Upload className="size-4" />}
            onClick={() => input.current?.click()}
          >
            {t("chooseFile")}
          </Button>
          {chosen ? (
            <span className="flex min-w-0 items-center gap-2 text-sm">
              <FileSpreadsheet aria-hidden className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{chosen.name}</span>
              <span className="shrink-0 text-muted-foreground">
                {formatBytes(chosen.size, format)}
              </span>
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">{t("noFileChosen")}</span>
          )}
        </div>

        <p className="text-sm text-muted-foreground">{t("nothingHappensYet")}</p>

        {upload.error ? <Alert tone="danger">{upload.error.message}</Alert> : null}

        <Button
          variant="primary"
          disabled={!chosen}
          busy={upload.isPending}
          onClick={() => upload.mutate()}
        >
          {t("readIt")}
        </Button>
      </CardBody>
    </Card>
  );
}

/**
 * Steps 3 and 4 — what the columns mean, and who decided.
 *
 * Every column is listed, including the ones nothing matched, so "we ignored six columns" is
 * something the person read rather than something they find out afterwards.
 */
function MapColumns({
  record,
  onChanged,
  onConfirmed,
}: {
  record: ImportSummary;
  onChanged: (summary: ImportSummary) => void;
  onConfirmed: (summary: ImportSummary) => void;
}) {
  const t = useTranslations("import");
  const suggestions = useMemo(() => {
    const proposal = record.proposal as
      | { suggestions?: { column: string; field: string; confidence: number }[] }
      | null
      | undefined;
    return new Map(
      (proposal?.suggestions ?? []).map((item) => [item.column, item] as const),
    );
  }, [record.proposal]);

  const [mapping, setMappingState] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(record.column_mapping as Record<string, { field: string }>).map(
        ([column, value]) => [column, value.field],
      ),
    ),
  );

  const propose = useMutation({
    mutationFn: () => proposeMapping(record.id),
    onSuccess: onChanged,
  });
  const confirm = useMutation({
    mutationFn: () => setMapping(record.id, mapping, record.version),
    onSuccess: onConfirmed,
  });

  const consulted = (record.proposal as { consulted?: boolean } | null)?.consulted;
  const reason = (record.proposal as { reason?: string } | null)?.reason;

  return (
    <Card>
      <CardHeader
        title={t("mapTitle")}
        description={t("mapBody")}
        action={
          record.ignored_columns.length > 0 && record.proposal === null ? (
            <Button
              size="sm"
              icon={<Sparkles className="size-3.5" />}
              busy={propose.isPending}
              onClick={() => propose.mutate()}
            >
              {t("askForHelp")}
            </Button>
          ) : undefined
        }
      />
      <CardBody className="space-y-4">
        {/*  The model's part, stated exactly. Never "AI mapped your file" — it was asked about
            the headings nothing matched, and only those. */}
        {consulted === false ? (
          <Alert tone="info" title={t("noModelTitle")}>
            {reason ? `${reason} ${t("noModelBody")}` : t("noModelBody")}
          </Alert>
        ) : null}
        {consulted === true ? (
          <Alert tone="info" title={t("proposedTitle")}>
            {t("proposedBody", { count: suggestions.size })}
          </Alert>
        ) : null}

        <ul className="divide-y divide-border rounded-lg border border-border">
          {record.source_columns.map((column) => {
            const suggestion = suggestions.get(column);
            const current = mapping[column] ?? "";
            return (
              <li
                key={column}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{column}</span>
                  {suggestion && current !== suggestion.field ? (
                    <button
                      type="button"
                      className="text-xs text-primary underline underline-offset-4"
                      onClick={() =>
                        setMappingState({ ...mapping, [column]: suggestion.field })
                      }
                    >
                      {t("useSuggestion", { field: t(`fields.${suggestion.field}`) })}
                    </button>
                  ) : null}
                </span>

                <span className="flex shrink-0 items-center gap-2">
                  {current === "" ? <Badge tone="neutral">{t("ignored")}</Badge> : null}
                  <label className="sr-only" htmlFor={`map-${column}`}>
                    {t("meansFor", { column })}
                  </label>
                  <select
                    id={`map-${column}`}
                    value={current}
                    onChange={(event) => {
                      const next = { ...mapping };
                      if (event.target.value) next[column] = event.target.value;
                      else delete next[column];
                      setMappingState(next);
                    }}
                    className="h-8 rounded-md border border-border bg-card px-2 text-sm"
                  >
                    <option value="">{t("ignoreThisColumn")}</option>
                    {FIELD_NAMES.map((field) => (
                      <option
                        key={field}
                        value={field}
                        disabled={
                          mapping[column] !== field &&
                          Object.values(mapping).includes(field)
                        }
                      >
                        {t(`fields.${field}`)}
                      </option>
                    ))}
                  </select>
                </span>
              </li>
            );
          })}
        </ul>

        {propose.error ? <Alert tone="danger">{propose.error.message}</Alert> : null}
        {confirm.error ? <Alert tone="danger">{confirm.error.message}</Alert> : null}

        <Button
          variant="primary"
          busy={confirm.isPending}
          disabled={!Object.values(mapping).includes("unit_name")}
          onClick={() => confirm.mutate()}
        >
          {t("continueToReview")}
        </Button>
        {!Object.values(mapping).includes("unit_name") ? (
          <p className="text-sm text-muted-foreground">{t("needDepartmentColumn")}</p>
        ) : null}
      </CardBody>
    </Card>
  );
}

/**
 * The fields the importer understands.
 *
 * Mirrors `parsing.FIELDS` on the server. Listed here rather than fetched because the labels are
 * translated, and a translated label cannot come from an API response without shipping the
 * catalogue to the server.
 */
const FIELD_NAMES = [
  "unit_name",
  "parent_name",
  "unit_type",
  "unit_ref",
  "position_title",
  "position_ref",
  "location",
  "person_email",
  "person_name",
  "effective_from",
] as const;

/** Steps 5 and 6 — the rows, what is wrong with them, and the tree that would result. */
function Review({
  record,
  onBack,
  onApplied,
}: {
  record: ImportSummary;
  onBack: () => void;
  onApplied: () => void;
}) {
  const preview = useQuery({
    queryKey: ["hierarchy", "import", record.id],
    queryFn: ({ signal }) => fetchPreview(record.id, signal),
  });
  const apply = useMutation({
    mutationFn: () => applyImport(record.id, record.version),
    onSuccess: onApplied,
  });

  return (
    <QueryStates
      isPending={preview.isPending}
      error={preview.error}
      onRetry={() => void preview.refetch()}
    >
      {preview.data ? (
        <ReviewBody
          preview={preview.data}
          busy={apply.isPending}
          error={apply.error}
          onBack={onBack}
          onApply={() => apply.mutate()}
        />
      ) : null}
    </QueryStates>
  );
}

function ReviewBody({
  preview,
  busy,
  error,
  onBack,
  onApply,
}: {
  preview: ImportPreview;
  busy: boolean;
  error: Error | null;
  onBack: () => void;
  onApply: () => void;
}) {
  const t = useTranslations("import");
  const broken = preview.rows.filter((row) => row.errors.length > 0);
  const warned = preview.rows.filter(
    (row) => row.errors.length === 0 && row.warnings.length > 0,
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t("reviewTitle")}
          description={t("reviewBody", {
            rows: preview.row_count,
            units: preview.proposed_tree.length,
          })}
        />
        <CardBody className="space-y-4">
          {preview.ignored_columns.length > 0 ? (
            <Alert tone="info" title={t("ignoringTitle")}>
              {preview.ignored_columns.join(", ")}
            </Alert>
          ) : null}

          {preview.error_count > 0 ? (
            <Alert tone="danger" title={t("errorsTitle", { count: preview.error_count })}>
              <ul className="mt-1 space-y-0.5">
                {broken.slice(0, 10).map((row) => (
                  <li key={row.row_number}>
                    {t("onRow", { row: row.row_number })} — {row.errors.join(" ")}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : null}

          {warned.length > 0 ? (
            <Alert tone="warning" title={t("warningsTitle", { count: warned.length })}>
              <ul className="mt-1 space-y-0.5">
                {warned.slice(0, 5).map((row) => (
                  <li key={row.row_number}>
                    {t("onRow", { row: row.row_number })} — {row.warnings.join(" ")}
                  </li>
                ))}
              </ul>
            </Alert>
          ) : null}
        </CardBody>
      </Card>

      <Card as="section">
        <CardHeader title={t("treeTitle")} description={t("treeBody")} />
        <CardBody>
          {preview.proposed_tree.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("treeEmpty")}</p>
          ) : (
            <ul className="space-y-2">
              {preview.proposed_tree.map((unit) => (
                <li key={unit.name} className="rounded-md bg-muted/50 px-3 py-2">
                  <p className="text-sm font-medium">
                    {unit.name}
                    {unit.parent_name ? (
                      <span className="font-normal text-muted-foreground">
                        {" "}
                        {t("under", { parent: unit.parent_name })}
                      </span>
                    ) : (
                      <span className="font-normal text-muted-foreground">
                        {" "}
                        {t("atTheTop")}
                      </span>
                    )}
                  </p>
                  {unit.positions.length > 0 ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {unit.positions
                        .map((position) =>
                          (position as { title: string }).title,
                        )
                        .join(" · ")}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {error ? <Alert tone="danger">{error.message}</Alert> : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          busy={busy}
          disabled={!preview.can_apply}
          onClick={onApply}
        >
          {t("applyIt")}
        </Button>
        <Button variant="ghost" onClick={onBack}>
          {t("backToMapping")}
        </Button>
        {!preview.can_apply ? (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <AlertTriangle aria-hidden className="size-4" />
            {t("cannotApplyYet")}
          </span>
        ) : null}
      </div>
    </div>
  );
}
