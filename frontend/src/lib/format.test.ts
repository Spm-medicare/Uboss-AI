/**
 * Formatting — 1.7.3.
 *
 * Exit check: **the same instant renders correctly for two people in different timezones.**
 *
 * That is not a formatting nicety. "Due 30 September" is a different moment in Mumbai and in New
 * York, and an approval that expired an hour ago in one of them is how somebody misses a thing
 * they were watching for.
 */

import { describe, expect, it } from "vitest";

import {
  contextFor,
  formatBytes,
  formatDate,
  formatDateTimeWithZone,
  formatMoney,
  formatNumber,
  formatRelative,
  instant,
} from "./format";

//  Late evening in London, which is already the next day in India. The clearest case: the
//  calendar date itself differs, not just the clock.
const MOMENT = "2026-09-29T20:30:00Z";

describe("the same instant, two people", () => {
  it("shows a different local time to each", () => {
    const mumbai = formatDateTimeWithZone(MOMENT, contextFor("Asia/Kolkata"));
    const newYork = formatDateTimeWithZone(MOMENT, contextFor("America/New_York"));

    expect(mumbai).not.toBe(newYork);
    expect(mumbai).toContain("2:00");   // 01:00 next day, +5:30
    expect(newYork).toContain("4:30");  // same evening, -4
  });

  it("shows a different calendar date to each", () => {
    //  Asserted on the day, not on the word order — that belongs to the locale, and DR-002 has
    //  not chosen one. What matters is that the two people see different days.
    const mumbai = formatDate(MOMENT, contextFor("Asia/Kolkata"));
    const newYork = formatDate(MOMENT, contextFor("America/New_York"));

    expect(mumbai).toContain("30");
    expect(newYork).toContain("29");
    expect(mumbai).not.toBe(newYork);
  });

  it("names the zone, so a time is a fact rather than a guess", () => {
    expect(formatDateTimeWithZone(MOMENT, contextFor("Asia/Kolkata"))).toMatch(/GMT|IST/);
  });

  it("falls back to UTC rather than to the browser's zone", () => {
    //  Someone travelling should still see their team's schedule in their team's time, not in
    //  whatever airport they are sitting in.
    expect(contextFor(undefined).timeZone).toBe("UTC");
    expect(contextFor("").timeZone).toBe("UTC");
  });
});

describe("parsing", () => {
  it("throws on a value that is not an instant", () => {
    //  Rather than becoming `Invalid Date` and rendering those two words onto a page.
    expect(() => instant("not a date")).toThrow();
  });

  it("accepts what the API sends", () => {
    expect(instant(MOMENT).toISOString()).toBe("2026-09-29T20:30:00.000Z");
  });
});

describe("relative time", () => {
  const now = new Date("2026-09-29T20:30:00Z");

  it("reads naturally in both directions", () => {
    const ctx = contextFor("UTC");
    expect(formatRelative("2026-09-27T20:30:00Z", ctx, now)).toBe("2 days ago");
    expect(formatRelative("2026-10-02T20:30:00Z", ctx, now)).toBe("in 3 days");
    expect(formatRelative("2026-09-29T19:30:00Z", ctx, now)).toBe("1 hour ago");
  });
});

describe("numbers", () => {
  it("groups the way the locale does", () => {
    expect(formatNumber(1234567, contextFor("UTC"))).toBe("1,234,567");
  });

  it("reads sizes in the units a file manager uses", () => {
    const ctx = contextFor("UTC");
    expect(formatBytes(512, ctx)).toBe("512 B");
    expect(formatBytes(1_400_000, ctx)).toBe("1.4 MB");
    //  Decimal, not binary: a "1 MB limit" must not reject a file the operating system calls 1 MB.
    expect(formatBytes(1_000_000, ctx)).toBe("1 MB");
  });

  it("never assumes a currency", () => {
    const ctx = contextFor("UTC");
    expect(formatMoney(1500, "INR", ctx)).toContain("₹");
    expect(formatMoney(1500, "USD", ctx)).toContain("$");
  });
});
