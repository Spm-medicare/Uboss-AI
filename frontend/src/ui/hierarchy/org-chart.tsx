"use client";

import { UserRound, UserRoundX } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import type { OrgUnitRead, PositionRead } from "@/lib/api/contract";
import { cn } from "@/lib/cn";

/**
 * The company as a chart — boxes, connector lines, one colour per level.
 *
 * The list view beside it is the one to work in: it holds the buttons, it stays readable at four
 * hundred nodes, and it is what a screen reader can navigate. **This view answers a different
 * question**, and it is the one people actually open an org chart to ask — *what shape is this
 * organisation, and where do I sit in it?* An indented list can be read for that; a chart is
 * seen for it, which is not the same effort.
 *
 * ## The three things this gets right that a naive chart does not
 *
 * **Vacant seats are drawn.** A position exists whether or not somebody is in it, and a chart
 * that only draws people hides the empty seats — which are the hiring plan. A vacant box is
 * outlined rather than filled and says "Vacant" in words, because `ui/README.md` forbids
 * colour-only status and an empty box could as easily be a rendering fault.
 *
 * **Colour is decoration, not meaning.** Depth already shows in the position, the connectors and
 * the unit-type badge. The ramp exists so a wide chart can be scanned, and nothing is only
 * knowable from it — print this in greyscale and no fact is lost.
 *
 * **Nothing is invented to make it pretty.** No head-count roll-ups, no percentages, no photos.
 * Every box shows what the server sent for that unit and no more.
 *
 * ## How the lines are drawn
 *
 * CSS borders on pseudo-elements, not SVG. The layout is a centred flex row of subtrees, so each
 * child already knows where it sits; a stem down from the parent, a rail across the children and
 * a stem up into each child is four rules and reflows correctly at any width. An SVG overlay
 * would need measured coordinates, which means a layout pass, a resize observer and a class of
 * bug where the lines are a frame behind the boxes.
 */

/** How many levels have their own colour before the ramp repeats. Matches the tokens. */
const LEVELS = 6;

function levelColour(depth: number): string {
  //  Wraps rather than clamping. A tree deeper than the ramp is unusual, and repeating the
  //  sequence keeps adjacent levels distinct, which clamping to one colour would not.
  return `var(--ub-level-${depth % LEVELS})`;
}

export function OrgChart({
  units,
  actions,
}: {
  units: OrgUnitRead[];
  /**
   * The controls for one box — adding a sub-unit, adding a seat.
   *
   * Passed in rather than built here, so the chart and the list offer the *same* buttons doing
   * the same thing. Two implementations of "add a department" is two behaviours that drift, and
   * the one people reach for is whichever screen they happen to be on.
   *
   * Absent for somebody who may not edit: the page decides that once, from the session, and this
   * component never second-guesses it.
   */
  actions?: (unit: OrgUnitRead) => ReactNode;
}) {
  const byParent = new Map<string | null, OrgUnitRead[]>();
  for (const unit of units) {
    const bucket = byParent.get(unit.parent_id) ?? [];
    bucket.push(unit);
    byParent.set(unit.parent_id, bucket);
  }
  const roots = byParent.get(null) ?? [];

  return (
    //  The chart is as wide as the organisation, which is wider than the page for anything real.
    //  It scrolls inside its own box so the page itself never scrolls sideways.
    <div className="overflow-x-auto pb-2">
      <div className="flex min-w-max justify-center gap-8 px-4 pt-2">
        {roots.map((unit) => (
          <Subtree
            key={unit.id}
            unit={unit}
            byParent={byParent}
            depth={0}
            actions={actions}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * One unit and everything under it.
 *
 * The stems are on this element rather than on the box, so a subtree carries its own connection
 * to its parent and can be dropped anywhere in the row without the parent knowing about it.
 */
function Subtree({
  unit,
  byParent,
  depth,
  actions,
}: {
  unit: OrgUnitRead;
  byParent: Map<string | null, OrgUnitRead[]>;
  depth: number;
  //  `| undefined` explicitly: `exactOptionalPropertyTypes` treats "absent" and "present and
  //  undefined" as different types, and this is passed straight down from a parent that may
  //  hold the second.
  actions: ((unit: OrgUnitRead) => ReactNode) | undefined;
}) {
  const children = byParent.get(unit.id) ?? [];

  return (
    <div className="flex flex-col items-center">
      <UnitBox unit={unit} depth={depth} actions={actions} />

      {children.length > 0 ? (
        <>
          {/*  The stem down out of this box. */}
          <span
            aria-hidden
            className="h-6 w-px shrink-0"
            style={{ backgroundColor: levelColour(depth) }}
          />

          <div className="flex items-start">
            {children.map((child, index) => (
              <div key={child.id} className="flex flex-col items-center px-4">
                {/*  The rail across the children, in two halves per cell: the left half is
                    drawn unless this is the first child, the right half unless it is the last.
                    So the rail spans exactly from the first child's stem to the last child's
                    and stops — rather than hanging past both ends, which is the detail that
                    separates a chart that looks drawn from one that looks nearly drawn.
                    A single child gets neither half, only the stem, which is what a chart does. */}
                <span aria-hidden className="flex h-px w-full">
                  <span
                    className="h-px flex-1"
                    style={{
                      backgroundColor: index > 0 ? levelColour(depth) : "transparent",
                    }}
                  />
                  <span
                    className="h-px flex-1"
                    style={{
                      backgroundColor:
                        index < children.length - 1 ? levelColour(depth) : "transparent",
                    }}
                  />
                </span>
                {/*  The stem up into the child. */}
                <span
                  aria-hidden
                  className="h-6 w-px shrink-0"
                  style={{ backgroundColor: levelColour(depth) }}
                />
                <Subtree
                  unit={child}
                  byParent={byParent}
                  depth={depth + 1}
                  actions={actions}
                />
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** One department, with the seats inside it and the controls that change it. */
function UnitBox({
  unit,
  depth,
  actions,
}: {
  unit: OrgUnitRead;
  depth: number;
  actions: ((unit: OrgUnitRead) => ReactNode) | undefined;
}) {
  const t = useTranslations("hierarchy");
  const colour = levelColour(depth);
  const controls = actions?.(unit);

  //  Seniority first. `level` is the organisation's own grade — 1 is the most senior — and
  //  without this the head of a department appears wherever it happened to be created, which on
  //  a chart reads as an ordering that means something and does not.
  //
  //  A seat with no level sorts last rather than first: an ungraded seat is not senior to a
  //  graded one, and putting it at the top would be the chart asserting something the data does
  //  not say. Ties fall back to the title so the order is stable between renders.
  const positions = [...(unit.positions ?? [])].sort((left, right) => {
    const byLevel = (left.level ?? Number.MAX_SAFE_INTEGER) - (right.level ?? Number.MAX_SAFE_INTEGER);
    return byLevel !== 0 ? byLevel : left.title.localeCompare(right.title);
  });

  return (
    <div className="w-56 overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {/*  The coloured header is the level. The badge under it says the same thing in words, so
          the colour never carries it alone. */}
      <div className="px-3.5 py-2.5 text-white" style={{ backgroundColor: colour }}>
        <p className="truncate text-sm font-semibold" title={unit.name}>
          {unit.name}
        </p>
        <p className="mt-0.5 text-[0.6875rem] font-medium uppercase tracking-[0.08em] text-white/80">
          {t(`unitType.${unit.unit_type}`)}
        </p>
      </div>

      {positions.length === 0 ? (
        <p className="px-3.5 py-3 text-xs text-muted-foreground">{t("noPositions")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {positions.map((position) => (
            <Seat key={position.id} position={position} colour={colour} />
          ))}
        </ul>
      )}

      {/*  On the card, not on the coloured header: a ghost button on a saturated fill either
          disappears or has to be restyled per level, and the second is six variants of one
          control. Under the seats it also sits where "add another one" belongs. */}
      {controls ? (
        <div className="flex items-center gap-1 border-t border-border bg-muted/40 px-2 py-1.5">
          {controls}
        </div>
      ) : null}
    </div>
  );
}

/**
 * One seat — the person's name over the job title, as an org chart has always shown it.
 *
 * A vacant seat keeps its row. It is the seat that exists, not the person, and a chart that drops
 * the row when nobody is in it silently deletes the open headcount from the picture.
 */
function Seat({ position, colour }: { position: PositionRead; colour: string }) {
  const t = useTranslations("hierarchy");
  const holder = position.holder ?? null;

  return (
    <li className="flex items-center gap-2.5 px-3.5 py-2.5">
      <span
        aria-hidden
        className={cn(
          "grid size-8 shrink-0 place-items-center rounded-full text-white",
          holder ? "" : "border border-dashed bg-transparent",
        )}
        style={
          holder
            ? { backgroundColor: colour }
            : { borderColor: colour, color: "var(--ub-text-muted)" }
        }
      >
        {holder ? (
          <UserRound className="size-4" />
        ) : (
          <UserRoundX className="size-4" />
        )}
      </span>

      <span className="min-w-0 flex-1">
        {holder ? (
          <span className="block truncate text-sm font-medium" title={holder.display_name}>
            {holder.display_name}
          </span>
        ) : (
          //  In words, not only in outline. Somebody scanning for open seats is scanning for
          //  this, and it must survive greyscale, a screenshot and a screen reader.
          <span className="block text-sm font-medium text-muted-foreground">
            {t("vacant")}
          </span>
        )}
        <span className="block truncate text-xs text-muted-foreground" title={position.title}>
          {position.title}
        </span>
      </span>
    </li>
  );
}
