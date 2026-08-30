import type { ReactNode } from "react";

/**
 * The heading a screen opens with.
 *
 * **The top bar names the room; this names the task.** They are not the same job. The bar is
 * chrome — it says "Agent Builder" in the same place on every screen and a person stops reading
 * it within a day. A page that then opens with a card and no sentence gives somebody who arrived
 * from a link nothing to orient on, and that is exactly how four builder screens looked before
 * this existed: an empty card floating in white space.
 *
 * One component rather than a heading written into each page, because four hand-rolled headings
 * drift in a week — different sizes, different spacing, one with a description and three without.
 *
 * `h2`, not `h1`: the shell already puts the screen's name in an `h1`, and a second one would
 * make the document outline claim two top-level headings. `aside` is for a control that belongs
 * to the whole screen — a date the page answers as at, a filter — rather than to one panel.
 */
export function PageHeader({
  title,
  description,
  aside,
}: {
  title: string;
  description?: string;
  /** A screen-wide control. Sits beside the heading on wide screens, under it on narrow ones. */
  aside?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div>
        <h2 className="text-[1.5rem] font-bold leading-tight tracking-tight">{title}</h2>
        {description ? (
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {aside ? <div className="shrink-0">{aside}</div> : null}
    </div>
  );
}
