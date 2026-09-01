/**
 * Which of the four form hues belongs to which Agent.
 *
 * The hues are not decoration and this mapping is not new. `tokens.css` says why they exist:
 * *"This is how the client recognises which form they are looking at — they say 'the blue one' —
 * so the hue is part of the vocabulary rather than decoration."* Each Builder already paints its
 * section bars with one, and the numbers come from the approved workbook's own form numbers, not
 * from a designer's preference:
 *
 * * Objective Agent Builder → Form 2 → `form-2`, blue
 * * Job Builder            → Form 3 → `form-3`, teal
 * * Agent Builder          → Form 4 → `form-4`, amber
 * * Supervisor Agent       → `form-1`, violet
 *
 * What this file adds is **consistency outside the form**. The list cards and the Dashboard were
 * uniformly grey, so the hue a person learns inside the Job Builder told them nothing on the way
 * in. Now the teal card leads to the teal form.
 *
 * **The colour is never the only signal**, which `ui/README.md` requires. Every card carries its
 * name, its ordinal and its status word; the hue reinforces all three and replaces none of them.
 *
 * The four semantic colours are deliberately untouched by this: §29 reserves amber for
 * approvals and warnings, green for success and red for errors. An identity hue must never be
 * read as a state, which is why these are the *form* tokens and not those.
 */

export type AgentToneId = "form-1" | "form-2" | "form-3" | "form-4";

/** Keyed by the navigation item id, so the sidebar, the Dashboard and the lists agree. */
export const AGENT_TONE: Record<string, AgentToneId> = {
  objectiveBuilder: "form-2",
  jobBuilder: "form-3",
  agentBuilder: "form-4",
  supervisor: "form-1",
};

interface ToneStyle {
  /** The full-strength hue: an accent rail, an icon. */
  accent: string;
  /** The wash: an icon chip, a hover tint. */
  soft: string;
}

const STYLES: Record<AgentToneId, ToneStyle> = {
  "form-1": { accent: "var(--ub-form-1)", soft: "var(--ub-form-1-soft)" },
  "form-2": { accent: "var(--ub-form-2)", soft: "var(--ub-form-2-soft)" },
  "form-3": { accent: "var(--ub-form-3)", soft: "var(--ub-form-3-soft)" },
  "form-4": { accent: "var(--ub-form-4)", soft: "var(--ub-form-4-soft)" },
};

/**
 * The inline custom properties a card sets, so its children can use them.
 *
 * Custom properties rather than Tailwind classes because the four hues are *data* — a lookup by
 * agent — and a class name cannot be looked up. Both tokens flip in dark mode on their own, so
 * nothing here needs a dark variant.
 */
export function toneVars(tone: AgentToneId): React.CSSProperties {
  const style = STYLES[tone];
  return {
    ["--card-accent" as string]: style.accent,
    ["--card-soft" as string]: style.soft,
  };
}

/** The tone for a navigation item id, falling back to violet for anything unmapped. */
export function toneFor(id: string): AgentToneId {
  return AGENT_TONE[id] ?? "form-1";
}
