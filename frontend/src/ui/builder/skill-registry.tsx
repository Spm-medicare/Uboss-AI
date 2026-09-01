"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Ban,
  Check,
  CircleAlert,
  Layers,
  Plus,
  Search,
  ShieldQuestion,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type {
  AgentSkillRead,
  CandidateOutcome,
  RequirementIn,
  ResolutionRead,
  SkillCard,
} from "@/lib/api/contract";
import { fetchRegistryLists, resolveRequirement, searchSkills } from "@/lib/api/skills";
import { cn } from "@/lib/cn";
import { Alert, Badge, Button, Field, Input, QueryStates, Textarea } from "@/ui";
import { SkillDrafts } from "@/ui/builder/skill-drafts";

/**
 * The Skill Registry, inside the Agent Builder.
 *
 * `PLAN.md` §39: *"Skill Registry is internal to Agent Builder and is not a sidebar module."*
 * There is no route and no menu entry — this panel is the whole of it, and §3 forbids adding one.
 *
 * Three tabs, which are `docs/product/SKILL_REGISTRY.md`'s own three: Registry, Resolver and
 * Private Skill Drafts.
 *
 * **The search discovers; the gates decide.** They are two separate acts on this screen because
 * they are two separate acts in the design. *Browse* ranks by resemblance and every card carries
 * the skill's exclusions and its autonomy, because nothing on that list has passed anything.
 * *Resolve* runs the deterministic gates and comes back with a route and the reason for it —
 * including, when it refuses, the catalogue's own words.
 *
 * **Nothing here is invented.** Every number, verdict and sentence on this panel came from the
 * response. There is no match percentage and no confidence score: `text_match` is Postgres's
 * ranking value and is shown as an ordinal position, because a percentage would read as
 * certainty the backend never claimed.
 */
export function SkillRegistry({
  attached,
  department,
  industry,
  disabled,
  onAttach,
  onDetach,
}: {
  attached: AgentSkillRead[];
  department: string | null;
  industry: string | null;
  disabled: boolean;
  onAttach: (skillId: string, decisionId: string | null, route: string | null) => void;
  onDetach: (skillId: string) => void;
}) {
  const t = useTranslations("registry");
  const [mode, setMode] = useState<"browse" | "resolve" | "drafts">("browse");
  //  The same query the filters use, so the counts cost nothing extra.
  const counts = useQuery({
    queryKey: ["registry-lists"],
    queryFn: ({ signal }) => fetchRegistryLists(signal),
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div className="space-y-4">
      {/*  Shown once the numbers have arrived, not before. This sentence used to state a figure
          nobody had counted — on a production path, four lines below this file's own promise that
          nothing here is invented — and a count is not a thing to guess at while a request is
          still out. */}
      {counts.data ? (
        <div className="rounded-lg border border-border bg-muted/30 p-3">
          <p className="text-sm text-muted-foreground">
            {counts.data.workspaceSkills > 0
              ? t("intro", {
                  catalogue: counts.data.catalogueSkills,
                  mine: counts.data.workspaceSkills,
                })
              : t("introCatalogueOnly", { catalogue: counts.data.catalogueSkills })}
          </p>
        </div>
      ) : null}

      {attached.length > 0 ? (
        <Attached rows={attached} disabled={disabled} onDetach={onDetach} />
      ) : null}

      <div
        role="tablist"
        aria-label={t("modes")}
        className="flex gap-1 rounded-lg border border-border bg-card p-1"
      >
        {(["browse", "resolve", "drafts"] as const).map((option) => (
          <button
            key={option}
            type="button"
            role="tab"
            aria-selected={mode === option}
            onClick={() => setMode(option)}
            className={cn(
              "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150",
              "motion-reduce:transition-none",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              mode === option
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent",
            )}
          >
            {t(`mode.${option}`)}
          </button>
        ))}
      </div>

      {mode === "browse" ? (
        <Browse
          department={department}
          industry={industry}
          attached={attached}
          disabled={disabled}
          onAttach={(skillId) => onAttach(skillId, null, null)}
        />
      ) : mode === "resolve" ? (
        <Resolve
          department={department}
          industry={industry}
          attached={attached}
          disabled={disabled}
          onAttach={onAttach}
        />
      ) : (
        /*  `docs/product/SKILL_REGISTRY.md`'s own tree has three things under Skills: Registry,
            Resolver and Private Skill Drafts. This is the third, and it is where the resolver's
            *Create* route finally leads. */
        <SkillDrafts disabled={disabled} />
      )}
    </div>
  );
}

// ------------------------------------------------------------------------- what is attached

function Attached({
  rows,
  disabled,
  onDetach,
}: {
  rows: AgentSkillRead[];
  disabled: boolean;
  onDetach: (skillId: string) => void;
}) {
  const t = useTranslations("registry");

  return (
    <section aria-labelledby="attached-skills" className="space-y-2">
      <h3 id="attached-skills" className="text-sm font-medium">
        {t("attachedTitle", { count: rows.length })}
      </h3>
      <ul className="space-y-2">
        {rows.map((row) => (
          <li
            key={row.id}
            className="rounded-lg border border-border bg-card p-3 text-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium leading-snug">{row.name}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {row.catalogue_id ? (
                    <Badge tone="neutral">{row.catalogue_id}</Badge>
                  ) : (
                    <Badge tone="human">{t("privateDraft")}</Badge>
                  )}
                  <Badge tone="neutral">{row.autonomy}</Badge>
                  {/*  The route is the resolver's, copied from the decision. A skill attached
                      without one says so rather than implying it was reasoned about. */}
                  {row.route ? (
                    <Badge tone="success">{t(`route.${row.route}`)}</Badge>
                  ) : (
                    <Badge tone="approval">{t("noDecision")}</Badge>
                  )}
                </div>
              </div>
              {!disabled ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<X className="size-3.5" />}
                  onClick={() => onDetach(row.skill_id)}
                >
                  {t("remove")}
                </Button>
              ) : null}
            </div>

            {/*  Carried onto the card rather than a click away: what a skill is *not* for is what
                stops a plausible choice from being the wrong one, and no gate decides it. */}
            {row.exclusions ? (
              <p className="mt-2 flex gap-1.5 border-t border-border pt-2 text-xs text-muted-foreground">
                <Ban aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                <span>{row.exclusions}</span>
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------------------- browse

function Browse({
  department,
  industry,
  attached,
  disabled,
  onAttach,
}: {
  department: string | null;
  industry: string | null;
  attached: AgentSkillRead[];
  disabled: boolean;
  onAttach: (skillId: string) => void;
}) {
  const t = useTranslations("registry");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  const vocabulary = useQuery({
    queryKey: ["registry-lists"],
    queryFn: ({ signal }) => fetchRegistryLists(signal),
    staleTime: 5 * 60 * 1000,
  });

  const [layer, setLayer] = useState("");

  const results = useQuery({
    queryKey: ["skills", submitted, layer, department, industry],
    queryFn: ({ signal }) =>
      searchSkills({
        signal,
        ...(submitted ? { q: submitted } : {}),
        ...(layer ? { layer } : {}),
        ...(department ? { department } : {}),
        ...(industry ? { industry } : {}),
      }),
    enabled: submitted.length > 0 || layer.length > 0,
  });

  const taken = new Set(attached.map((row) => row.skill_id));

  return (
    <div className="space-y-3">
      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <div className="flex-1">
          <Field label={t("searchLabel")} htmlFor="skill-search">
            {(field) => (
              <Input
                {...field}
                value={query}
                placeholder={t("searchPlaceholder")}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
          </Field>
        </div>
        <Button type="submit" variant="secondary" icon={<Search className="size-3.5" />}>
          {t("search")}
        </Button>
      </form>

      {vocabulary.data && vocabulary.data.layers.length > 1 ? (
        <div className="flex flex-wrap gap-1.5">
          {["", ...vocabulary.data.layers].map((option) => (
            <button
              key={option || "all"}
              type="button"
              aria-pressed={layer === option}
              onClick={() => setLayer(option)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors duration-150",
                "motion-reduce:transition-none",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
                layer === option
                  ? "border-[var(--ub-brand)] bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-accent",
              )}
            >
              {option || t("allLayers")}
            </button>
          ))}
        </div>
      ) : null}

      {submitted || layer ? (
        <QueryStates
          isPending={results.isPending}
          error={results.error}
          onRetry={() => void results.refetch()}
        >
          {results.data?.isEmpty ? (
            <Alert tone="info">{t("nothingFound")}</Alert>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {t("resultCount", { count: results.data?.total ?? 0 })}
              </p>
              <ul className="space-y-2">
                {(results.data?.results ?? []).map((card) => (
                  <li key={card.id}>
                    <SkillResult
                      card={card}
                      attached={taken.has(card.id)}
                      disabled={disabled}
                      onAttach={() => onAttach(card.id)}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
        </QueryStates>
      ) : (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {t("browseHint")}
        </p>
      )}
    </div>
  );
}

function SkillResult({
  card,
  attached,
  disabled,
  onAttach,
}: {
  card: SkillCard;
  attached: boolean;
  disabled: boolean;
  onAttach: () => void;
}) {
  const t = useTranslations("registry");

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug">{card.name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
            {/*  Where it ranked, not how confident anything is. */}
            <span className="text-muted-foreground">{t("rank", { rank: card.rank })}</span>
            {card.catalogue_id ? <Badge tone="neutral">{card.catalogue_id}</Badge> : null}
            <Badge tone="neutral">{card.autonomy}</Badge>
            {card.is_catalogue ? null : <Badge tone="human">{t("privateDraft")}</Badge>}
          </div>
        </div>
        {attached ? (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Check aria-hidden className="size-3.5" />
            {t("alreadyAttached")}
          </span>
        ) : !disabled ? (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus className="size-3.5" />}
            onClick={onAttach}
          >
            {t("attach")}
          </Button>
        ) : null}
      </div>

      {card.purpose ? (
        <p className="mt-2 text-xs text-muted-foreground">{card.purpose}</p>
      ) : null}

      {card.exclusions ? (
        <p className="mt-2 flex gap-1.5 border-t border-border pt-2 text-xs">
          <Ban aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span>
            <span className="font-medium">{t("notFor")}</span>{" "}
            <span className="text-muted-foreground">{card.exclusions}</span>
          </span>
        </p>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------------- resolve

function Resolve({
  department,
  industry,
  attached,
  disabled,
  onAttach,
}: {
  department: string | null;
  industry: string | null;
  attached: AgentSkillRead[];
  disabled: boolean;
  onAttach: (skillId: string, decisionId: string | null, route: string | null) => void;
}) {
  const t = useTranslations("registry");
  const [need, setNeed] = useState("");
  const [autonomy, setAutonomy] = useState("A1");
  const [evidence, setEvidence] = useState(false);
  const [inputs, setInputs] = useState<string[]>([]);

  const resolve = useMutation({
    mutationFn: (): Promise<ResolutionRead> => {
      const requirement: RequirementIn = {
        need: need.trim(),
        autonomy_ceiling: autonomy,
        evidence_required: evidence,
        available_inputs: inputs,
        ...(department ? { department } : {}),
        ...(industry ? { industry } : {}),
      };
      return resolveRequirement(requirement);
    },
  });

  const resolution = resolve.data;
  const taken = new Set(attached.map((row) => row.skill_id));

  return (
    <div className="space-y-4">
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          resolve.mutate();
        }}
      >
        <Field label={t("needLabel")} htmlFor="requirement-need" required>
          {(field) => (
            <Textarea
              {...field}
              rows={2}
              value={need}
              placeholder={t("needPlaceholder")}
              onChange={(event) => setNeed(event.target.value)}
            />
          )}
        </Field>

        <div className="flex flex-wrap items-end gap-4">
          <Field label={t("autonomyLabel")} htmlFor="requirement-autonomy" hint={t("autonomyHint")}>
            {(field) => (
              <select
                {...field}
                value={autonomy}
                onChange={(event) => setAutonomy(event.target.value)}
                className="h-9 rounded-md border border-border bg-card px-2 text-sm"
              >
                {["A1", "A2", "A3", "A4"].map((level) => (
                  <option key={level} value={level}>
                    {t(`autonomy.${level}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <label className="flex items-center gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={evidence}
              onChange={(event) => setEvidence(event.target.checked)}
              className="size-4 rounded border-border"
            />
            {t("evidenceRequired")}
          </label>

          <span className="ml-auto">
            <Button
              type="submit"
              variant="primary"
              busy={resolve.isPending}
              disabled={!need.trim()}
            >
              {t("resolve")}
            </Button>
          </span>
        </div>
      </form>

      {/*  A failure renders as a failure. Never a toast that says it worked. */}
      {resolve.isError ? (
        <Alert tone="danger">
          {resolve.error instanceof Error ? resolve.error.message : t("resolveFailed")}
        </Alert>
      ) : null}

      {resolution ? (
        <Resolution
          resolution={resolution}
          taken={taken}
          disabled={disabled}
          onAttach={onAttach}
          onSupplyInputs={(missing) =>
            setInputs((current) => Array.from(new Set([...current, ...missing])))
          }
        />
      ) : null}
    </div>
  );
}

const ROUTE_TONE: Record<string, "success" | "human" | "approval" | "neutral"> = {
  reuse: "success",
  configure: "human",
  compose: "human",
  create: "approval",
  blocked: "approval",
};

function Resolution({
  resolution,
  taken,
  disabled,
  onAttach,
  onSupplyInputs,
}: {
  resolution: ResolutionRead;
  taken: Set<string>;
  disabled: boolean;
  onAttach: (skillId: string, decisionId: string | null, route: string | null) => void;
  onSupplyInputs: (missing: string[]) => void;
}) {
  const t = useTranslations("registry");
  const candidates = resolution.candidates ?? [];
  const unevaluated = resolution.unevaluated_gates ?? [];

  return (
    <div className="space-y-3">
      <div
        className={cn(
          "rounded-lg border p-3",
          resolution.route === "blocked"
            ? "border-approval bg-approval-soft"
            : "border-[var(--ub-brand)] bg-muted/30",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={ROUTE_TONE[resolution.route] ?? "neutral"}>
            {t(`route.${resolution.route}`)}
          </Badge>
          {resolution.requires_confirmation ? (
            <Badge tone="approval">{t("needsConfirmation")}</Badge>
          ) : null}
        </div>
        <p className="mt-2 text-sm">{resolution.rationale}</p>
      </div>

      {/*  Gates that could not run. Reported as open questions, never as passes — the resolution
          says so itself with `requires_confirmation`. */}
      {unevaluated.length > 0 ? (
        <details className="rounded-lg border border-border bg-card p-3">
          <summary className="cursor-pointer text-sm font-medium">
            <span className="inline-flex items-center gap-1.5">
              <ShieldQuestion aria-hidden className="size-3.5" />
              {t("unevaluated", { count: unevaluated.length })}
            </span>
          </summary>
          <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
            {unevaluated.map((gate) => (
              <li key={gate.gate}>
                <span className="font-medium text-foreground">{gate.name}</span> — {gate.reason}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {candidates.length > 0 ? (
        <section aria-labelledby="candidates" className="space-y-2">
          <h3 id="candidates" className="text-sm font-medium">
            {t("candidates", { count: candidates.length })}
          </h3>
          <ul className="space-y-2">
            {candidates.map((candidate) => (
              <li key={candidate.skill_id}>
                <Candidate
                  candidate={candidate}
                  decisionId={resolution.decision_id}
                  route={resolution.route}
                  selected={resolution.selected_skill_id === candidate.skill_id}
                  attached={taken.has(candidate.skill_id)}
                  disabled={disabled}
                  onAttach={onAttach}
                  onSupplyInputs={onSupplyInputs}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Candidate({
  candidate,
  decisionId,
  route,
  selected,
  attached,
  disabled,
  onAttach,
  onSupplyInputs,
}: {
  candidate: CandidateOutcome;
  decisionId: string;
  route: string;
  selected: boolean;
  attached: boolean;
  disabled: boolean;
  onAttach: (skillId: string, decisionId: string | null, route: string | null) => void;
  onSupplyInputs: (missing: string[]) => void;
}) {
  const t = useTranslations("registry");
  const gates = candidate.gates ?? [];
  const failures = gates.filter((gate) => gate.outcome === "failed");
  const missing = failures.flatMap((gate) => gate.missing ?? []);

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-3",
        selected ? "border-[var(--ub-brand)]" : "border-border",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug">{candidate.name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-muted-foreground">{t("rank", { rank: candidate.rank })}</span>
            {candidate.catalogue_id ? (
              <Badge tone="neutral">{candidate.catalogue_id}</Badge>
            ) : null}
            <Badge tone="neutral">{candidate.autonomy}</Badge>
            {candidate.passed ? (
              <Badge tone="success">{t("passedAll")}</Badge>
            ) : (
              <Badge tone="approval">{t("refused", { count: failures.length })}</Badge>
            )}
          </div>
        </div>

        {/*  Only a candidate that passed every gate can be attached from here. Similarity never
            overrides a hard gate, and a button that let it would be the place that broke it. */}
        {attached ? (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Check aria-hidden className="size-3.5" />
            {t("alreadyAttached")}
          </span>
        ) : candidate.passed && !disabled ? (
          <Button
            variant={selected ? "primary" : "ghost"}
            size="sm"
            icon={<Plus className="size-3.5" />}
            onClick={() => onAttach(candidate.skill_id, decisionId, route)}
          >
            {t("attach")}
          </Button>
        ) : null}
      </div>

      {failures.length > 0 ? (
        <ul className="mt-2 space-y-1.5 border-t border-border pt-2">
          {failures.map((gate) => (
            <li key={gate.gate} className="flex gap-1.5 text-xs">
              <CircleAlert
                aria-hidden
                className="mt-0.5 size-3.5 shrink-0 text-approval"
              />
              <span>
                {/*  The catalogue's own words, when one of the twelve says exactly this. */}
                {gate.failure_state ? (
                  <span className="font-medium">{gate.failure_state} — </span>
                ) : (
                  <span className="font-medium">{gate.name} — </span>
                )}
                <span className="text-muted-foreground">{gate.reason}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {/*  The only refusal with a named remedy, so it is the only one offering a button. */}
      {missing.length > 0 && !disabled ? (
        <Button
          variant="ghost"
          size="sm"
          className="mt-2"
          icon={<Layers className="size-3.5" />}
          onClick={() => onSupplyInputs(missing)}
        >
          {t("supplyInputs", { count: missing.length })}
        </Button>
      ) : null}

      {candidate.exclusions ? (
        <p className="mt-2 flex gap-1.5 border-t border-border pt-2 text-xs">
          <Ban aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          <span>
            <span className="font-medium">{t("notFor")}</span>{" "}
            <span className="text-muted-foreground">{candidate.exclusions}</span>
          </span>
        </p>
      ) : null}
    </div>
  );
}
