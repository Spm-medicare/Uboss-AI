"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, ExternalLink, Send, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { askCopilot } from "@/lib/api/copilot";
import type { CopilotAnswer, CopilotPreview, CopilotSource } from "@/lib/api/contract";
import { cn } from "@/lib/cn";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { ErrorState } from "@/ui/states";

/**
 * §29's *"optional right Copilot/help drawer"*, once there is something behind it.
 *
 * Three things on this screen are the product's honesty, not its decoration:
 *
 * **Every answer is labelled a proposal.** §18: *"clearly labels proposal versus saved state"*.
 * The backend sends `proposal: true` on every answer and this shows it every time — not only when
 * a change is attached. A person reading a side panel while doing something else needs to know
 * without asking that nothing here has happened.
 *
 * **Grounded and ungrounded look different.** `grounded` is computed on the server by checking the
 * model's citations against what retrieval actually returned. When it is false the answer is a
 * guess and is shown as one, with its sources labelled *"what matched"* rather than *"sources"*.
 * The alternative — one presentation for both — is the specific dishonesty the 2026-08-22 audit
 * found three times in this frontend.
 *
 * **A change is a difference and a link, never a button that saves.** There is no route to apply
 * one; `preview.py` explains why the absence is the design. What the panel offers is the shortest
 * honest path: here is what would change, open it and decide.
 *
 * Nothing is kept. The panel holds one exchange in component state and the drawer discards it on
 * close, because §18 says *"chat history is not the authoritative object record"* and a stored
 * transcript would be a second copy of company data with none of the retention rules that govern
 * the first.
 */
export function CopilotPanel({ onNavigate }: { onNavigate: () => void }) {
  const t = useTranslations("copilot");
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  const ask = useMutation({
    mutationFn: (text: string) => askCopilot(text),
    onSuccess: () => box.current?.focus(),
  });

  function submit() {
    const text = question.trim();
    if (!text || ask.isPending) return;
    setAsked(text);
    ask.mutate(text);
  }

  return (
    <div className="flex h-full flex-col">
      <div
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
        aria-live="polite"
        aria-busy={ask.isPending}
      >
        {ask.isIdle ? <WhatItDoes /> : null}

        {asked && !ask.isIdle ? (
          <p className="text-sm font-medium">{asked}</p>
        ) : null}

        {ask.isPending ? (
          <p className="text-sm text-muted-foreground">{t("reading")}</p>
        ) : null}

        {ask.isError ? (
          <ErrorState error={ask.error as Error} onRetry={() => ask.mutate(asked)} />
        ) : null}

        {ask.data ? <Answer answer={ask.data} onNavigate={onNavigate} /> : null}
      </div>

      <form
        className="shrink-0 border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label htmlFor="copilot-question" className="sr-only">
          {t("questionLabel")}
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id="copilot-question"
            ref={box}
            rows={2}
            value={question}
            maxLength={2000}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              //  Enter sends, Shift+Enter starts a line. The convention every chat box uses, and
              //  worth following exactly: a person typing a question does not expect to reach for
              //  a button.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={t("placeholder")}
            className={cn(
              "min-h-[3.5rem] w-full resize-none rounded-md border border-border bg-card",
              "px-3 py-2 text-sm placeholder:text-muted-foreground",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
            )}
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            busy={ask.isPending}
            disabled={question.trim().length === 0}
            icon={<Send className="size-3.5" />}
            aria-label={t("send")}
          />
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("notKept")}</p>
      </form>
    </div>
  );
}

/**
 * What it can and cannot do, before anybody has asked anything.
 *
 * The refusals are stated up front rather than discovered. Somebody who learns halfway through a
 * week that the Copilot cannot publish has spent the week expecting it to.
 */
function WhatItDoes() {
  const t = useTranslations("copilot");

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Sparkles aria-hidden className="size-4 text-ai" />
        {t("introTitle")}
      </div>
      <p className="text-sm text-muted-foreground">{t("introBody")}</p>
      <p className="text-sm text-muted-foreground">{t("introRefusals")}</p>
    </div>
  );
}

function Answer({
  answer,
  onNavigate,
}: {
  answer: CopilotAnswer;
  onNavigate: () => void;
}) {
  const t = useTranslations("copilot");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {/*  §18. Shown on every answer, not only on the ones carrying a change. */}
        <Badge tone="ai" icon={<Sparkles className="size-3" />}>
          {t("proposalLabel")}
        </Badge>
        {answer.grounded ? (
          <Badge tone="success" outline>
            {t("groundedIn", { count: answer.sources.length })}
          </Badge>
        ) : (
          <Badge tone="approval" outline>
            {t("notGrounded")}
          </Badge>
        )}
      </div>

      {answer.model_unavailable ? (
        <Alert tone="info" title={t("noModelTitle")}>
          {t("noModelBody")}
        </Alert>
      ) : null}

      {/*  Somebody put an instruction in a record. The person reading this is the one who can go
          and look at whose record it was. */}
      {answer.injection_noticed ? (
        <Alert tone="warning" title={t("injectionTitle")}>
          {t("injectionBody")}
        </Alert>
      ) : null}

      <p className="whitespace-pre-wrap text-sm leading-relaxed">{answer.text}</p>

      {!answer.grounded && !answer.model_unavailable ? (
        <p className="text-xs text-muted-foreground">{t("notGroundedWhy")}</p>
      ) : null}

      {answer.change ? (
        <ChangePreview change={answer.change} onNavigate={onNavigate} />
      ) : null}

      {answer.sources.length > 0 ? (
        <Sources
          sources={answer.sources}
          grounded={answer.grounded}
          onNavigate={onNavigate}
        />
      ) : null}
    </div>
  );
}

/**
 * The difference, and the way to go and make it.
 *
 * `current` came from the row and `proposed` came from the model, which is the only arrangement
 * worth showing: a diff whose two sides came from the same place is two sentences with a label.
 *
 * The link is a link. It does not save, it does not pre-fill through a query parameter, and it
 * carries no token — the person opens the object, sees the field, and types or pastes. Anything
 * shorter than that would be this panel making the change with an extra click in front of it.
 */
function ChangePreview({
  change,
  onNavigate,
}: {
  change: CopilotPreview;
  onNavigate: () => void;
}) {
  const t = useTranslations("copilot");

  return (
    <section className="rounded-md border border-border bg-card">
      <header className="border-b border-border px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("proposedChange")}
        </p>
        <p className="truncate text-sm font-medium">{change.label}</p>
      </header>

      {change.refused ? (
        <div className="p-3">
          <Alert tone="warning" title={t("cannotChangeTitle")}>
            {change.refused}
          </Alert>
        </div>
      ) : (
        <>
          <dl className="divide-y divide-border">
            {change.changes.map((item) => (
              <div key={item.field} className="space-y-1.5 px-3 py-2.5">
                <dt className="text-xs font-medium text-muted-foreground">
                  {item.label}
                </dt>
                <dd className="space-y-1.5 text-sm">
                  <p className="rounded bg-danger-soft/40 px-2 py-1 text-muted-foreground line-through decoration-1">
                    {item.current || t("emptyToday")}
                  </p>
                  <p className="rounded bg-success-soft/50 px-2 py-1">{item.proposed}</p>
                </dd>
              </div>
            ))}
          </dl>
          <footer className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
            <p className="text-xs text-muted-foreground">{t("nothingSaved")}</p>
            <a
              href={change.href}
              onClick={onNavigate}
              className={cn(
                "inline-flex shrink-0 items-center gap-1 rounded-md border border-border",
                "bg-card px-2.5 py-1 text-xs font-medium hover:bg-accent",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              )}
            >
              {t("openToChange")}
              <ArrowRight aria-hidden className="size-3" />
            </a>
          </footer>
        </>
      )}
    </section>
  );
}

/**
 * Where the answer came from — §18: *"Shows sources/object references when using company data."*
 *
 * The heading changes with `grounded`, because the list means two different things. On a grounded
 * answer these are the objects it drew on. On an ungrounded one they are only what matched the
 * words, and calling them sources would dress a guess up as a citation.
 */
function Sources({
  sources,
  grounded,
  onNavigate,
}: {
  sources: CopilotSource[];
  grounded: boolean;
  onNavigate: () => void;
}) {
  const t = useTranslations("copilot");

  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {grounded ? t("sources") : t("matched")}
      </h3>
      <ul className="space-y-1">
        {sources.map((source) => (
          <li key={`${source.kind}-${source.id}`}>
            <a
              href={source.href}
              onClick={onNavigate}
              className={cn(
                "flex items-start gap-2 rounded-md border border-border bg-card px-2.5 py-2",
                "text-sm hover:bg-accent",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{source.label}</span>
                <span className="block text-xs text-muted-foreground">
                  {t(`kind.${source.kind}` as "kind.objective")}
                </span>
              </span>
              <ExternalLink aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
