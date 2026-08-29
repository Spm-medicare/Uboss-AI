import { cn } from "@/lib/cn";

/**
 * A grey block standing where content will be.
 *
 * Use it only where the *shape* of what is coming is already known — a fixed table, a profile
 * header. Where the shape depends on the response, it guesses, and a layout that jumps when the
 * data arrives is worse than a spinner that did not pretend.
 *
 * Hidden from assistive technology. The region it lives in carries `aria-busy`; a screen reader
 * announcing eight grey rectangles is noise.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-muted", className)}
    />
  );
}
