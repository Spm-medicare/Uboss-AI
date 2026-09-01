"use client";

import {
  Check,
  CornerUpRight,
  MessageSquare,
  ShieldCheck,
  Star,
  TrendingUp,
  Undo2,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { cn } from "@/lib/cn";
import type { PersonRef, TaskDetail } from "@/lib/api/contract";
import { Badge, Button, Field, Input, Textarea } from "@/ui";

import { KIND_TONE, STATE_TONE } from "./tone";

/** The outcomes each kind of task may end with — the same three sets the service enforces. */
const OUTCOMES: Record<string, readonly string[]> = {
  approval: ["approved", "rejected", "changes_requested"],
  input: ["provided"],
  work: ["completed"],
};

/**
 * One task, opened.
 *
 * **Every control here is one the backend has a route for.** `CLAUDE.md`: never show a control
 * that does not do what it says. Attaching evidence is not offered — uploading a file against a
 * task is 7.6's, and a button opening a picker that led nowhere would be worse than its absence.
 *
 * The outcomes offered depend on the kind. Offering *Approve* on a piece of work would produce a
 * refusal a person could do nothing about; offering *Complete* on an approval would let somebody
 * close a decision without making one.
 */
export function TaskPanel({
  task,
  people,
  busy,
  canAct,
  formatWhen,
  onStart,
  onComplete,
  onDecline,
  onDelegate,
  onComment,
  onFollow,
  onEscalate,
  onClose,
}: {
  task: TaskDetail;
  people: readonly PersonRef[];
  busy: boolean;
  /** Theirs, or unassigned and they may hand work out. Re-checked by the server regardless. */
  canAct: boolean;
  formatWhen: (iso: string) => string;
  onStart: () => void;
  onComplete: (outcome: string, note?: string) => void;
  onDecline: (reason: string) => void;
  onDelegate: (to: string, note?: string) => void;
  onComment: (body: string) => void;
  onFollow: () => void;
  /** Put another name on a decision nobody is making. Approval tasks only. */
  onEscalate: (to: string | undefined, note: string) => void;
  onClose: () => void;
}) {
  const t = useTranslations("todo");
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [handingTo, setHandingTo] = useState("");
  //  Which secondary form is open. One at a time: a footer showing a decline box and a delegate
  //  box together asks somebody to answer two questions in order to do one thing.
  const [mode, setMode] = useState<"none" | "decline" | "delegate" | "escalate">(
    "none",
  );

  const open = task.state === "pending" || task.state === "in_progress";
  const outcomes = OUTCOMES[task.kind] ?? OUTCOMES.work!;
  const approval = task.approval ?? null;
  //  For an approval the backend has already worked out whether this person may decide —
  //  the same three conditions the route enforces. Trusting it rather than re-deriving them
  //  keeps one rule in one place; a copy here would be a second implementation, and the one
  //  printed on the screen is the one people believe.
  const canDecide = approval ? approval.may_decide : canAct;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={KIND_TONE[task.kind] ?? "neutral"}>
              {t(`kinds.${task.kind}`)}
            </Badge>
            <Badge tone={STATE_TONE[task.state] ?? "neutral"} outline>
              {t(`states.${task.state}`)}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {t("stepOf", { position: task.step_position })}
            </span>
          </div>
          <h3 className="mt-2 text-base font-semibold leading-snug">{task.title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {task.assignee_name
              ? t("assignedTo", { name: task.assignee_name })
              : t("assignedToNobody")}
            {" · "}
            {t(`via.${task.assigned_via}`)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={task.following}
            icon={<Star className={cn("size-3.5", task.following && "fill-current")} />}
            onClick={onFollow}
          >
            {task.following ? t("unfollow") : t("follow")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("close")}
            icon={<X className="size-4" />}
            onClick={onClose}
          />
        </div>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {/*  The words the Job's author wrote, in the version this run pinned. Nothing is
            generated here: a step whose author left every field empty shows no instructions
            rather than a sentence this screen made up. */}
        {task.instructions ? (
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("instructions")}
            </h4>
            <dl className="mt-2 space-y-2.5">
              {task.instructions.split("\n").map((line) => {
                const at = line.indexOf(": ");
                const label = at > 0 ? line.slice(0, at) : null;
                const value = at > 0 ? line.slice(at + 2) : line;
                return (
                  <div key={line} className="text-sm">
                    {label ? (
                      <dt className="text-xs font-medium text-muted-foreground">
                        {label}
                      </dt>
                    ) : null}
                    <dd className="leading-relaxed">{value}</dd>
                  </div>
                );
              })}
            </dl>
          </section>
        ) : (
          <p className="text-sm text-muted-foreground">{t("noInstructions")}</p>
        )}

        {approval ? (
          <section className="rounded-lg border border-approval/30 bg-approval-soft/40 px-3.5 py-3">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-approval">
              <ShieldCheck aria-hidden className="size-3.5" />
              {t("approval.heading")}
            </h4>
            <p className="mt-2 text-sm leading-relaxed">
              {approval.question ?? t("approval.noQuestion")}
            </p>
            <dl className="mt-2 space-y-0.5 text-xs text-muted-foreground">
              <div>
                {t("approval.requestedBy", {
                  name: approval.requested_by_name ?? t("someone"),
                })}
              </div>
              <div>
                {approval.approver_name
                  ? t("approval.approver", { name: approval.approver_name })
                  : t("approval.approverNobody")}
              </div>
              {approval.escalated_to_name ? (
                <div>
                  {t("approval.escalatedTo", { name: approval.escalated_to_name })}
                </div>
              ) : null}
              {approval.escalation_note ? (
                <div>
                  {t("approval.escalationNote", { note: approval.escalation_note })}
                </div>
              ) : null}
            </dl>
            {approval.state === "withdrawn" ? (
              <p className="mt-2 text-xs font-medium">{t("approval.withdrawn")}</p>
            ) : null}
          </section>
        ) : null}

        {task.outcome ? (
          <section className="rounded-lg border border-border bg-muted/40 px-3.5 py-3">
            <p className="text-sm font-medium">{t(`outcomes.${task.outcome}`)}</p>
            {task.outcome_note ? (
              <p className="mt-1 text-sm text-muted-foreground">{task.outcome_note}</p>
            ) : null}
            {task.completed_at ? (
              <p className="mt-1.5 text-xs text-muted-foreground">
                {t("closedBy", {
                  name: task.completed_by_name ?? t("someone"),
                  when: formatWhen(task.completed_at),
                })}
              </p>
            ) : null}
          </section>
        ) : null}

        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("conversation")}
          </h4>
          {task.comments.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">{t("noComments")}</p>
          ) : (
            <ul className="mt-2 space-y-3">
              {task.comments.map((entry) => (
                <li key={entry.id} className="text-sm">
                  <p className="text-xs text-muted-foreground">
                    {entry.author_name ?? t("someone")} · {formatWhen(entry.created_at)}
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap leading-relaxed">
                    {entry.body}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <form
            className="mt-3 flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!comment.trim()) return;
              onComment(comment.trim());
              setComment("");
            }}
          >
            <Input
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder={t("commentPlaceholder")}
              aria-label={t("commentPlaceholder")}
            />
            <Button
              type="submit"
              size="sm"
              variant="secondary"
              busy={busy}
              disabled={!comment.trim()}
              icon={<MessageSquare className="size-3.5" />}
            >
              {t("send")}
            </Button>
          </form>
        </section>
      </div>

      {open && canDecide ? (
        <footer className="space-y-3 border-t border-border px-5 py-4">
          {mode === "decline" ? (
            <Field
              label={task.kind === "approval" ? t("rejectReason") : t("declineReason")}
              hint={t("declineHint")}
            >
              {(props) => (
                <Textarea
                  {...props}
                  rows={2}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              )}
            </Field>
          ) : null}
          {mode === "escalate" ? (
            <>
              <Field label={t("approval.escalateTo")} hint={t("approval.escalateHint")}>
                {(props) => (
                  <select
                    {...props}
                    value={handingTo}
                    onChange={(event) => setHandingTo(event.target.value)}
                    className="h-9 w-full rounded-lg border border-border bg-card px-3 text-sm"
                  >
                    <option value="">{t("choosePerson")}</option>
                    {people.map((person) => (
                      <option key={person.membership_id} value={person.membership_id}>
                        {person.display_name}
                        {person.job_title ? ` — ${person.job_title}` : ""}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label={t("approval.escalateNote")}>
                {(props) => (
                  <Textarea
                    {...props}
                    rows={2}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                  />
                )}
              </Field>
            </>
          ) : null}
          {mode === "delegate" ? (
            <Field label={t("delegateTo")} hint={t("delegateHint")}>
              {(props) => (
                <select
                  {...props}
                  value={handingTo}
                  onChange={(event) => setHandingTo(event.target.value)}
                  className="h-9 w-full rounded-lg border border-border bg-card px-3 text-sm"
                >
                  <option value="">{t("choosePerson")}</option>
                  {people.map((person) => (
                    <option key={person.membership_id} value={person.membership_id}>
                      {person.display_name}
                      {person.job_title ? ` — ${person.job_title}` : ""}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            {mode === "none" ? (
              <>
                {task.state === "pending" ? (
                  <Button size="sm" variant="secondary" busy={busy} onClick={onStart}>
                    {t("start")}
                  </Button>
                ) : null}
                {(canDecide ? outcomes : []).map((outcome) => (
                  <Button
                    key={outcome}
                    size="sm"
                    variant={outcome === "rejected" ? "danger" : "primary"}
                    busy={busy}
                    icon={<Check className="size-3.5" />}
                    onClick={() => {
                      //  A refusal must say why, so these open the box rather than sending
                      //  something the server would refuse.
                      if (outcome === "rejected" || outcome === "changes_requested") {
                        setMode("decline");
                        return;
                      }
                      onComplete(outcome);
                    }}
                  >
                    {t(`actions.${outcome}`)}
                  </Button>
                ))}
                {approval ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<TrendingUp className="size-3.5" />}
                    onClick={() => setMode("escalate")}
                  >
                    {t("approval.escalate")}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<CornerUpRight className="size-3.5" />}
                    onClick={() => setMode("delegate")}
                  >
                    {t("delegate")}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Undo2 className="size-3.5" />}
                  onClick={() => setMode("decline")}
                >
                  {t("handBack")}
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  busy={busy}
                  variant="primary"
                  disabled={
                    mode === "decline"
                      ? !note.trim()
                      : mode === "escalate"
                        ? handingTo.length === 0 && !note.trim()
                        : handingTo.length === 0
                  }
                  onClick={() => {
                    if (mode === "escalate") {
                      onEscalate(handingTo || undefined, note.trim());
                    } else if (mode === "delegate") {
                      onDelegate(handingTo, note.trim() || undefined);
                    } else if (task.kind === "approval") {
                      //  On an approval the reason box belongs to the rejection, so this
                      //  records a decision rather than handing the work back.
                      onComplete("rejected", note.trim());
                    } else {
                      onDecline(note.trim());
                    }
                    setNote("");
                    setHandingTo("");
                    setMode("none");
                  }}
                >
                  {t("confirm")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setMode("none");
                    setNote("");
                  }}
                >
                  {t("cancel")}
                </Button>
              </>
            )}
          </div>
        </footer>
      ) : null}

      {open && !canDecide ? (
        <footer className="border-t border-border px-5 py-4">
          {/*  Says which rule stopped them. A refusal with no reason is the message that
              generates the support ticket. */}
          <p className="text-sm text-muted-foreground">
            {approval &&
            approval.requested_by_membership_id ===
              approval.approver_membership_id
              ? t("approval.selfBlocked")
              : approval
                ? t("approval.notYours")
                : t("notYours")}
          </p>
        </footer>
      ) : null}
    </div>
  );
}
