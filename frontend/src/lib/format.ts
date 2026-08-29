/**
 * Turning stored values into something a person reads.
 *
 * PLAN §17: "Store instants UTC and explicit IANA timezones." Everything in the database is UTC.
 * Everything on screen is in the reader's own zone — which is not the same as the server's, and
 * not the same as the person sitting next to them.
 *
 * **The zone comes from the signed-in person**, falling back to their organisation's. The API
 * returns it on `/auth/me` and it is already resolved: `membership.timezone ?? tenant.timezone`.
 * The browser's own zone is deliberately not used — someone travelling should still see their
 * team's schedule in their team's time, not in whatever airport they are in.
 *
 * **A date without a zone is a bug waiting for a deadline.** "Due 30 September" means different
 * instants in Mumbai and New York, and an approval that expired an hour ago in one of them is
 * how a person misses something they were watching for.
 */

import { DEFAULT_LOCALE, type Locale } from "@/i18n/config";

/** A safe fallback when nobody has said otherwise. Never the browser's — see above. */
export const FALLBACK_TIME_ZONE = "UTC";

export interface FormatContext {
  locale: Locale;
  timeZone: string;
}

export function contextFor(
  timeZone: string | undefined,
  locale: Locale = DEFAULT_LOCALE,
): FormatContext {
  return { locale, timeZone: timeZone || FALLBACK_TIME_ZONE };
}

/**
 * Parse what the API sent.
 *
 * The API sends ISO 8601 with an offset, so this is unambiguous. An invalid value throws rather
 * than becoming `Invalid Date` and rendering as the literal string "Invalid Date" on a page —
 * which is what happens when nobody checks, and it looks like a product that does not work.
 */
export function instant(value: string | Date): Date {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Not a valid instant: ${String(value)}`);
  }
  return date;
}

/** A date, as that person's zone sees it. "29 August 2026". */
export function formatDate(value: string | Date, context: FormatContext): string {
  return new Intl.DateTimeFormat(context.locale, {
    dateStyle: "long",
    timeZone: context.timeZone,
  }).format(instant(value));
}

/** A date and time, with the zone named. */
export function formatDateTime(
  value: string | Date,
  context: FormatContext,
): string {
  return new Intl.DateTimeFormat(context.locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: context.timeZone,
  }).format(instant(value));
}

/**
 * A date and time with its zone shown.
 *
 * Used wherever the exact instant matters and the reader may not be in the zone it is written
 * for — a schedule, an approval deadline, an audit entry. The abbreviation is what turns
 * "3:00 pm" from a guess into a fact.
 */
export function formatDateTimeWithZone(
  value: string | Date,
  context: FormatContext,
): string {
  //  Explicit components rather than `dateStyle`/`timeStyle`. Intl refuses to combine either of
  //  those with `timeZoneName`, and the zone is the whole point of this variant.
  return new Intl.DateTimeFormat(context.locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: context.timeZone,
    timeZoneName: "short",
  }).format(instant(value));
}

/** Just the time. "3:00 pm". */
export function formatTime(value: string | Date, context: FormatContext): string {
  return new Intl.DateTimeFormat(context.locale, {
    timeStyle: "short",
    timeZone: context.timeZone,
  }).format(instant(value));
}

/**
 * "in 3 days", "2 hours ago".
 *
 * Relative to *now*, so it is only correct at the moment it renders. Fine for "last seen" and
 * wrong for a deadline: a person planning around "in 3 days" needs the date, and this is the
 * form that hides it. Where both matter, show this and the absolute date together.
 */
export function formatRelative(
  value: string | Date,
  context: FormatContext,
  now: Date = new Date(),
): string {
  const target = instant(value);
  const seconds = Math.round((target.getTime() - now.getTime()) / 1000);

  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3600],
    ["minute", 60],
  ];

  const formatter = new Intl.RelativeTimeFormat(context.locale, {
    numeric: "auto",
  });

  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) {
      return formatter.format(Math.trunc(seconds / size), unit);
    }
  }
  return formatter.format(seconds, "second");
}

/** A plain number, grouped the way this locale groups them. */
export function formatNumber(
  value: number,
  context: FormatContext,
  options: Intl.NumberFormatOptions = {},
): string {
  return new Intl.NumberFormat(context.locale, options).format(value);
}

/**
 * A size a person can read. "1.4 MB".
 *
 * Decimal units, because that is what a file manager and a storage bill both use. Binary units
 * would make a "1 MB limit" reject a file the operating system calls 1 MB.
 */
export function formatBytes(bytes: number, context: FormatContext): string {
  if (bytes < 1000) return `${formatNumber(bytes, context)} B`;

  const units = ["kB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${formatNumber(value, context, {
    maximumFractionDigits: value < 10 ? 1 : 0,
  })} ${units[unit]}`;
}

/**
 * Money, in the currency it is actually in.
 *
 * The currency is a parameter and never assumed. A number rendered as ₹ when it is $ is not a
 * formatting bug, it is a wrong figure in front of somebody making a decision.
 */
export function formatMoney(
  amount: number,
  currency: string,
  context: FormatContext,
): string {
  return new Intl.NumberFormat(context.locale, {
    style: "currency",
    currency,
  }).format(amount);
}
