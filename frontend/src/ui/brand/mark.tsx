"use client";

/**
 * The UBOSS AI mark.
 *
 * **This file is the whole logo.** Everything else imports from here, so replacing the official
 * artwork is a one-file change rather than a hunt through the application. If a designer supplies
 * an `.svg`, its `<path>` data goes into `MONOGRAM_PATHS` and `Wordmark` below; nothing that uses
 * `Logo` needs to know.
 *
 * Drawn as SVG rather than an image file for three reasons that matter here: it stays crisp at
 * every size including a 16px favicon, it takes its colour from `currentColor` so the same mark
 * works on the dark sidebar and a light page without a second asset, and it adds no network
 * request to a screen somebody is waiting on.
 *
 * The geometry is a reconstruction from the supplied artwork — a `U` with a squared top and a
 * fully rounded bowl, interlocked with a `B` whose top-left corner is cut on the diagonal. It is
 * faithful rather than traced; swap in the original when it is available.
 */

import { useState } from "react";
import type { SVGProps } from "react";

import { cn } from "@/lib/cn";

/**
 * Where the official artwork goes.
 *
 * The supplied file lives at `public/brand/uboss-logo.jpeg` and is what the full lockup renders.
 * Replacing it — with a transparent PNG or an SVG, which would both sit better on a dark panel —
 * is a change to `ARTWORK` and nothing else.
 *
 * The swap is done with an `onError` fallback rather than a build-time check because the file is
 * supplied by a designer, not by this repository: a missing asset should degrade to the drawn
 * mark, not to a broken image.
 */
const ARTWORK = "/brand/uboss-logo.jpeg";

/**
 * The interlocking `UB`, on one 420×310 grid.
 *
 * Two closed paths. The `U` is a single outline — down the left stem, under the bowl on a
 * 93-radius arc, up the right stem and back along the inside on a 35-radius counter, which is
 * what keeps the stroke an even weight all the way round. The `B` is drawn with `evenodd` so its
 * two bowls read as holes rather than as filled shapes stacked on the spine.
 *
 * Both fill from `currentColor`. That is the reason this is SVG and not a file: the dark sidebar,
 * a light sign-in card and a 16px favicon are the same mark rather than three assets that drift.
 */
const MONOGRAM_PATHS: readonly { d: string; rule: "evenodd" | "nonzero" }[] = [
  {
    //  The U. `sweep 0` under the bowl and `sweep 1` back along the counter — the two arcs turn
    //  opposite ways because one is the outside of the curve and the other is the inside.
    d: "M22 8 V203 a93 93 0 0 0 186 0 V8 H150 V203 a35 35 0 0 1-70 0 V8 Z",
    rule: "nonzero",
  },
  {
    //  The B. The first line is the diagonal cut across the top-left corner — the one gesture
    //  that stops the mark reading as an ordinary sans-serif B, and the thing to preserve if the
    //  geometry is ever redrawn. Then the upper bowl, the wider lower bowl, and the two counters.
    d:
      "M196 62 L256 8 H318 a72 72 0 0 1 0 144 H330 a72 72 0 0 1 0 144 H196 Z" +
      "M256 54 H300 a37 37 0 0 1 0 75 H256 Z" +
      "M256 175 H312 a37 37 0 0 1 0 75 H256 Z",
    rule: "evenodd",
  },
];

export function Monogram({ className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 420 310"
      fill="none"
      aria-hidden
      className={cn("h-full w-auto", className)}
      {...rest}
    >
      {MONOGRAM_PATHS.map((path) => (
        <path key={path.d} d={path.d} fill="currentColor" fillRule={path.rule} />
      ))}
    </svg>
  );
}

/**
 * The wordmark — `UBOSS` in the product's own face, `AI AMS` beside it in the accent.
 *
 * **Text, not SVG.** It was SVG, with `<text>` on a 420×96 grid and a rule with a centre dot,
 * and it looked correct at the size it was drawn for and like noise at every other. Rendered at
 * the 16–20px the sidebar and the sign-in panel actually use, the letterspacing collapsed and
 * the rule read as a stray underline — a logo that is wrong at the two sizes it appears at is a
 * logo that is wrong.
 *
 * As text it takes the real font, hints properly at small sizes, wraps never, and needs no
 * viewBox arithmetic to sit on a baseline with an icon. Nothing is lost: a wordmark is type, and
 * this is type.
 *
 * `UBOSS` takes `currentColor` so it works on the navy panel and a light page alike. `AI AMS`
 * takes `accentClassName`, which defaults to the sky the dark surfaces use — a light surface
 * passes `text-primary` instead, because the brand blue on white is the accessible pairing and
 * sky-400 on white is not.
 */
export function Wordmark({
  className,
  accentClassName = "text-sky-400",
}: {
  className?: string;
  /** The colour of `AI AMS`. Defaults to the value that works on the dark surfaces. */
  accentClassName?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "select-none whitespace-nowrap font-semibold tracking-[0.01em]",
        className,
      )}
    >
      UBOSS <span className={accentClassName}>AI AMS</span>
    </span>
  );
}

/**
 * The mark as a screen uses it.
 *
 * `variant` decides how much of it appears, and the choice is always about space rather than
 * emphasis:
 *
 * * `full` — monogram above the wordmark. The sign-in card and anywhere with room.
 * * `horizontal` — monogram beside the product name. The expanded sidebar.
 * * `mark` — the monogram alone. A collapsed sidebar, a favicon, an avatar slot.
 *
 * The accessible name is on the wrapper, not the artwork: both SVGs are `aria-hidden`, so a
 * screen reader reads "UBOSS AI" once rather than describing two decorative graphics.
 */
export function Logo({
  variant = "full",
  className,
  label = "UBOSS AI",
}: {
  variant?: "full" | "horizontal" | "mark";
  className?: string;
  label?: string;
}) {
  //  The supplied artwork when it is there, the drawn mark when it is not. `onError` rather than
  //  a build-time check: the file comes from a designer, and a missing one should fall back to
  //  something correct rather than to a broken image.
  const [artworkFailed, setArtworkFailed] = useState(false);

  if (variant === "mark") {
    return (
      <span role="img" aria-label={label} className={cn("inline-flex", className)}>
        <Monogram />
      </span>
    );
  }

  if (variant === "horizontal") {
    return (
      <span
        role="img"
        aria-label={label}
        className={cn("inline-flex items-center gap-2.5", className)}
      >
        <Monogram className="h-6" />
        <Wordmark className="text-lg" accentClassName="text-primary" />
      </span>
    );
  }

  if (!artworkFailed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={ARTWORK}
        alt={label}
        className={cn("h-32 w-auto object-contain", className)}
        onError={() => setArtworkFailed(true)}
      />
    );
  }

  return (
    <span
      role="img"
      aria-label={label}
      className={cn("inline-flex flex-col items-center gap-4", className)}
    >
      <Monogram className="h-16" />
      <Wordmark className="text-2xl" accentClassName="text-primary" />
    </span>
  );
}
