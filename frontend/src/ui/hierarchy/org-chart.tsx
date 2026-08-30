"use client";

import { Pencil, Plus, UserRound, UserRoundX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, type ReactNode } from "react";

import type { OrgUnitRead, PositionRead } from "@/lib/api/contract";
import { cn } from "@/lib/cn";

/**
 * The company as a chart — every box a node, every line a real relationship.
 *
 * ## One node per person, not a list inside a department
 *
 * The first version drew a department as a box with its people stacked inside it, indented by
 * reporting level. It was compact and it was wrong: a manager with two reports looked like three
 * rows of a list, and "who works for whom" — the only question an org chart exists to answer —
 * had to be inferred from an indent. **Now each seat is its own node, under the node it reports
 * to, joined by a drawn line.** Two managers in one department are two branches, and the people
 * under each hang off their own.
 *
 * ## Colour belongs to the department, not the depth
 *
 * Every seat inside Engineering is Engineering's colour, all the way down. Colouring by depth
 * instead made a lead in Finance and a lead in Sales the same colour, and a lead and their own
 * report different ones — the opposite of what somebody scanning the chart wants to know, which
 * is *which part of the company is this?* The department is the answer, so the department owns
 * the hue.
 *
 * It stays decoration. The department node sits directly above with its name on it, so nothing is
 * knowable only from colour — print this in greyscale and no fact is lost.
 *
 * ## What is drawn that a naive chart leaves out
 *
 * **Vacant seats.** A position exists whether or not somebody is in it, and a chart of only
 * people hides the open headcount, which is the hiring plan. A vacant node is outlined rather
 * than filled and says "Vacant" in words.
 *
 * **A seat whose manager is in another department** is drawn under its own department rather than
 * under that manager. The line would otherwise cross the whole chart to a box three columns away,
 * and a crossed line in an org chart reads as an error rather than as a fact.
 *
 * ## How the lines are drawn
 *
 * CSS borders, not SVG. The layout is a centred flex row of subtrees, so each child already knows
 * where it sits: a stem down from the parent, a rail across the children, a stem up into each
 * child. Four rules, and it reflows correctly at any width. An SVG overlay needs measured
 * coordinates, which means a layout pass, a resize observer, and a class of bug where the lines
 * are a frame behind the boxes.
 */

/** How many departments get their own hue before the ramp repeats. Matches the tokens. */
const HUES = 6;

function hue(index: number): string {
  return `var(--ub-level-${index % HUES})`;
}

function wash(index: number): string {
  return `var(--ub-level-${index % HUES}-soft)`;
}

export function OrgChart({
  units,
  actions,
  seatAction,
  seatEdit,
}: {
  units: OrgUnitRead[];
  /**
   * The controls for one department node — adding to it, editing it.
   *
   * Passed in rather than built here, so the chart and the list offer the *same* buttons doing
   * the same thing. Two implementations of "add a department" is two behaviours that drift.
   */
  actions?: (unit: OrgUnitRead) => ReactNode;
  /** The `+` on a person: add somebody who reports to them. */
  seatAction?: (position: PositionRead) => void;
  /** The pencil on a person: change the title, grade or manager, or remove the seat. */
  seatEdit?: (position: PositionRead) => void;
}) {
  const byParent = new Map<string | null, OrgUnitRead[]>();
  for (const unit of units) {
    const bucket = byParent.get(unit.parent_id) ?? [];
    bucket.push(unit);
    byParent.set(unit.parent_id, bucket);
  }
  const roots = byParent.get(null) ?? [];

  //  Which hue each department owns. Assigned from the order the units arrive in and inherited by
  //  every unit and seat beneath it — so a team inside Engineering is Engineering's colour rather
  //  than a fourth one.
  const hueOf = new Map<string, number>();
  let taken = 0;
  function paint(unit: OrgUnitRead, inherited: number | null) {
    //  The company keeps hue 0; each department under it takes the next one along, and everything
    //  inside a department inherits that department's.
    const mine = inherited ?? (unit.parent_id === null ? 0 : (taken += 1));
    hueOf.set(unit.id, mine);
    for (const child of byParent.get(unit.id) ?? []) {
      paint(child, unit.parent_id === null ? null : mine);
    }
  }
  for (const root of roots) paint(root, null);

  //  A chart is wider than the screen the moment a company has five departments, and a scroll box
  //  opens at its left edge — which on a centred tree is empty space beside the first department,
  //  with the company itself off to the right. Centre it so the top of the organisation is the
  //  thing on screen.
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = scroller.current;
    if (!box) return;
    box.scrollLeft = (box.scrollWidth - box.clientWidth) / 2;
  }, [units.length]);

  return (
    <div ref={scroller} className="overflow-x-auto pb-4">
      <div className="flex min-w-max justify-center gap-6 px-6 pt-2">
        {roots.map((unit) => (
          <UnitSubtree
            key={unit.id}
            unit={unit}
            byParent={byParent}
            hueOf={hueOf}
            actions={actions}
            seatAction={seatAction}
            seatEdit={seatEdit}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * A department, then its people, then the departments inside it.
 *
 * People before sub-departments on purpose: the head of Engineering belongs directly under
 * Engineering, and a team inside it belongs under that head — putting the teams first would draw
 * a department's own staff below its sub-teams, which is not what the structure says.
 */
function UnitSubtree({
  unit,
  byParent,
  hueOf,
  actions,
  seatAction,
  seatEdit,
}: {
  unit: OrgUnitRead;
  byParent: Map<string | null, OrgUnitRead[]>;
  hueOf: Map<string, number>;
  actions: ((unit: OrgUnitRead) => ReactNode) | undefined;
  seatAction: ((position: PositionRead) => void) | undefined;
  seatEdit: ((position: PositionRead) => void) | undefined;
}) {
  const index = hueOf.get(unit.id) ?? 0;
  const childUnits = byParent.get(unit.id) ?? [];
  const seats = (unit.positions ?? []).filter((seat) => seat.archived_at === null);

  //  Grade first, then title. An ungraded seat sorts last: it is not senior to a graded one, and
  //  putting it first would be the chart asserting something the data does not say. The title
  //  breaks ties so the order is stable between renders.
  const sorted = [...seats].sort((left, right) => {
    const byLevel =
      (left.level ?? Number.MAX_SAFE_INTEGER) - (right.level ?? Number.MAX_SAFE_INTEGER);
    return byLevel !== 0 ? byLevel : left.title.localeCompare(right.title);
  });

  const here = new Set(seats.map((seat) => seat.id));
  const reportsByManager = new Map<string, PositionRead[]>();
  const topSeats: PositionRead[] = [];
  for (const seat of sorted) {
    const manager = seat.reports_to_position_id;
    if (manager && here.has(manager)) {
      reportsByManager.set(manager, [...(reportsByManager.get(manager) ?? []), seat]);
    } else {
      //  Reports to nobody, or to somebody in another department. Either way this is where the
      //  branch starts in this box.
      topSeats.push(seat);
    }
  }

  const branches: ReactNode[] = [
    ...topSeats.map((seat) => (
      <SeatSubtree
        key={seat.id}
        position={seat}
        reportsByManager={reportsByManager}
        index={index}
        seatAction={seatAction}
        seatEdit={seatEdit}
      />
    )),
    ...childUnits.map((child) => (
      <UnitSubtree
        key={child.id}
        unit={child}
        byParent={byParent}
        hueOf={hueOf}
        actions={actions}
        seatAction={seatAction}
        seatEdit={seatEdit}
      />
    )),
  ];

  return (
    <Branch index={index} branches={branches}>
      <UnitNode unit={unit} index={index} seats={seats.length} actions={actions} />
    </Branch>
  );
}

/** A person, then everybody who reports to them. */
function SeatSubtree({
  position,
  reportsByManager,
  index,
  seatAction,
  seatEdit,
}: {
  position: PositionRead;
  reportsByManager: Map<string, PositionRead[]>;
  index: number;
  seatAction: ((position: PositionRead) => void) | undefined;
  seatEdit: ((position: PositionRead) => void) | undefined;
}) {
  const reports = reportsByManager.get(position.id) ?? [];

  return (
    <Branch
      index={index}
      branches={reports.map((report) => (
        <SeatSubtree
          key={report.id}
          position={report}
          reportsByManager={reportsByManager}
          index={index}
          seatAction={seatAction}
          seatEdit={seatEdit}
        />
      ))}
    >
      <SeatNode position={position} index={index} seatAction={seatAction} seatEdit={seatEdit} />
    </Branch>
  );
}

/**
 * A node and the lines down to whatever hangs off it.
 *
 * One component for both kinds of node, so a department and a person connect to their children
 * with exactly the same geometry. Two copies of this drifted within a day the first time.
 */
function Branch({
  index,
  branches,
  children,
}: {
  index: number;
  branches: ReactNode[];
  children: ReactNode;
}) {
  const colour = hue(index);

  return (
    <div className="flex flex-col items-center">
      {children}

      {branches.length > 0 ? (
        <>
          {/*  The stem down out of this node. */}
          <span aria-hidden className="h-5 w-px shrink-0" style={{ backgroundColor: colour }} />

          <div className="flex items-start">
            {branches.map((branch, position) => (
              <div
                //  Positional on purpose: each branch is already keyed on its own id inside, and
                //  this index only decides which half of the rail the cell draws.
                key={position}
                className="flex flex-col items-center px-2"
              >
                {/*  The rail, in two halves per cell: the left half unless this is the first
                    child, the right half unless it is the last. So it spans from the first
                    child's stem to the last child's and stops, rather than hanging past both
                    ends — the detail that separates a chart that looks drawn from one that looks
                    nearly drawn. A single child gets neither half, only the stem. */}
                <span aria-hidden className="flex h-px w-full">
                  <span
                    className="h-px flex-1"
                    style={{ backgroundColor: position > 0 ? colour : "transparent" }}
                  />
                  <span
                    className="h-px flex-1"
                    style={{
                      backgroundColor:
                        position < branches.length - 1 ? colour : "transparent",
                    }}
                  />
                </span>
                {/*  The stem up into the child. */}
                <span
                  aria-hidden
                  className="h-5 w-px shrink-0"
                  style={{ backgroundColor: colour }}
                />
                {branch}
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** A department. Its name, what kind of unit it is, and the controls that change it. */
function UnitNode({
  unit,
  index,
  seats,
  actions,
}: {
  unit: OrgUnitRead;
  index: number;
  seats: number;
  actions: ((unit: OrgUnitRead) => ReactNode) | undefined;
}) {
  const t = useTranslations("hierarchy");
  const colour = hue(index);
  const controls = actions?.(unit);

  return (
    <div
      className="w-60 overflow-hidden rounded-xl border shadow-sm"
      style={{
        borderColor: `color-mix(in oklab, ${colour} 32%, transparent)`,
        backgroundColor: wash(index),
      }}
    >
      <div className="px-3.5 py-2.5 text-white" style={{ backgroundColor: colour }}>
        <p className="truncate text-sm font-semibold" title={unit.name}>
          {unit.name}
        </p>
        <p className="mt-0.5 flex items-center gap-1.5 text-[0.6875rem] font-medium uppercase tracking-[0.08em] text-white/80">
          {t(`unitType.${unit.unit_type}`)}
          {/*  A count of what is in it — a fact the chart already holds, which somebody otherwise
               has to work out by counting boxes. */}
          <span className="text-white/60">·</span>
          {t("seatCount", { count: seats })}
        </p>
      </div>

      {controls ? (
        <div
          className="flex items-center gap-1 border-t px-2 py-1.5"
          style={{ borderColor: `color-mix(in oklab, ${colour} 20%, transparent)` }}
        >
          {controls}
        </div>
      ) : null}
    </div>
  );
}

/**
 * One person, or one empty seat.
 *
 * The grade badge is what somebody chose when the seat was created — a grade, which stays true
 * whether or not they currently have reports. Whether anybody *does* report to them is drawn
 * instead, as the lines below the node, which cannot go stale because they are the data.
 */
function SeatNode({
  position,
  index,
  seatAction,
  seatEdit,
}: {
  position: PositionRead;
  index: number;
  seatAction: ((position: PositionRead) => void) | undefined;
  seatEdit: ((position: PositionRead) => void) | undefined;
}) {
  const t = useTranslations("hierarchy");
  const colour = hue(index);
  const holder = position.holder ?? null;
  const band = bandFor(position.level ?? null);

  return (
    <div
      className="group/seat relative w-52 rounded-xl border bg-card px-3 py-2.5 shadow-sm"
      style={{
        borderColor: holder
          ? `color-mix(in oklab, ${colour} 30%, transparent)`
          : "var(--ub-border)",
        //  A vacant seat is drawn as an outline. It is the one state somebody scans a chart for —
        //  and it says "Vacant" in words too, because `ui/README.md` forbids colour-only status.
        borderStyle: holder ? "solid" : "dashed",
      }}
    >
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className="grid size-8 shrink-0 place-items-center rounded-full text-white"
          style={
            holder
              ? { backgroundColor: colour }
              : {
                  backgroundColor: "transparent",
                  border: `1px dashed ${colour}`,
                  color: "var(--ub-text-muted)",
                }
          }
        >
          {holder ? <UserRound className="size-4" /> : <UserRoundX className="size-4" />}
        </span>

        <span className="min-w-0 flex-1">
          {holder ? (
            <span
              className="block truncate text-sm font-semibold leading-tight"
              title={holder.display_name}
            >
              {holder.display_name}
            </span>
          ) : (
            <span className="block text-sm font-semibold leading-tight text-muted-foreground">
              {t("vacant")}
            </span>
          )}
          <span
            className="mt-0.5 block truncate text-xs text-muted-foreground"
            title={position.title}
          >
            {position.title}
          </span>
        </span>
      </div>

      {band ? (
        <span
          className="mt-1.5 inline-block rounded-sm px-1.5 py-px text-[0.5625rem] font-semibold uppercase tracking-wide"
          style={{
            backgroundColor: `color-mix(in oklab, ${colour} 14%, transparent)`,
            color: `color-mix(in oklab, ${colour} 70%, var(--ub-text))`,
          }}
        >
          {t(`designations.${band}`)}
        </span>
      ) : null}

      {/*  Overlaid on the corner rather than laid out in the row: they appear on hover and on
          keyboard focus, and the space they would otherwise reserve is width the name needs. */}
      {seatEdit || seatAction ? (
        <span className="absolute right-1.5 top-1.5 flex gap-0.5 opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover/seat:opacity-100 motion-reduce:transition-none">
          {seatEdit ? (
            <RowButton
              label={t("editSeatFor", { title: position.title })}
              onClick={() => seatEdit(position)}
            >
              <Pencil aria-hidden className="size-3.5" />
            </RowButton>
          ) : null}
          {seatAction ? (
            <RowButton
              label={t("addUnderSeat", { title: position.title })}
              onClick={() => seatAction(position)}
            >
              <Plus aria-hidden className="size-3.5" />
            </RowButton>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}

function RowButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={cn(
        "grid size-6 place-items-center rounded-md bg-card text-muted-foreground shadow-sm",
        "transition-colors duration-150 hover:bg-accent hover:text-foreground motion-reduce:transition-none",
        "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ub-focus)]",
      )}
    >
      {children}
    </button>
  );
}

/**
 * `level` back to the band it was chosen from — for the two worth saying.
 *
 * Employee is deliberately absent: it is the default and it sat on four nodes out of five, paid
 * for in the width the names needed. A node with no badge reads correctly as somebody who is
 * neither an executive nor a manager. A grade this chart did not write — imported from a
 * customer's own scale — is left unlabelled rather than rounded into the nearest band, which
 * would put a word on screen that nobody chose.
 */
function bandFor(level: number | null): string | null {
  if (level === 1) return "executive";
  if (level === 2) return "manager";
  return null;
}
