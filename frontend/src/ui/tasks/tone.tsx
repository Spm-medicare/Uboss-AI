import type { BadgeProps } from "@/ui";

type Tone = NonNullable<BadgeProps["tone"]>;

/**
 * Which badge colour a kind and a state wear.
 *
 * In one place because the list and the panel both draw them, and two maps drift the week
 * somebody adds a state. The colour never carries the meaning on its own — every badge shows a
 * word, per `ui/README.md` — so these are reinforcement, not information.
 */
export const KIND_TONE: Record<string, Tone> = {
  work: "human",
  input: "hybrid",
  approval: "approval",
};

export const STATE_TONE: Record<string, Tone> = {
  pending: "neutral",
  in_progress: "ai",
  done: "success",
  declined: "danger",
  delegated: "neutral",
  cancelled: "neutral",
};
