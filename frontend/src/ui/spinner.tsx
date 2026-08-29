import { Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * The one spinner.
 *
 * Deliberately never a progress bar. A bar implies a known proportion, and almost nothing here
 * knows one — `ui/README.md` forbids fake progress for exactly that reason: a bar that sits at
 * 90% because somebody guessed is worse than no bar at all.
 *
 * It carries no label of its own. The thing that is waiting says what it is waiting for, and two
 * announcements for one wait is one too many for a screen reader.
 */
export function Spinner({
  className,
  size = "sm",
}: {
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <Loader2
      aria-hidden
      className={cn(
        "animate-spin",
        size === "sm" ? "size-4" : "size-5",
        //  Respected globally in `globals.css` as well; repeated here because a spinner is the
        //  one thing a person with vestibular sensitivity will meet on every screen.
        "motion-reduce:animate-[spin_1.5s_linear_infinite]",
        className,
      )}
    />
  );
}
