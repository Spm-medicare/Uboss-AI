import { describe, expect, it } from "vitest";

import { operationKey } from "./idempotency";

/**
 * The server's own rule, copied from `backend/src/uboss/core/idempotency.py`.
 *
 * Duplicated on purpose and marked as such: a test that imported the rule from the code under
 * test would pass when both were wrong together. This is the contract the header must satisfy,
 * written out as the server states it.
 */
const SERVER_RULE = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$/;

describe("operationKey", () => {
  it("accepts the name that used to break every create in the product", () => {
    //  `unit-create:root:UBOSS Demo` was refused for the space, and the person was told their
    //  Idempotency-Key was invalid for having typed a company name with two words in it.
    expect(operationKey("unit-create", "root", "UBOSS Demo")).toMatch(SERVER_RULE);
  });

  it("produces a key the server accepts, whatever somebody types", () => {
    const names = [
      "UBOSS Demo",
      "Sales & Marketing",
      "R&D / Platform",
      "Bäcker GmbH",
      "東京支社",
      "Ops (EMEA) — 2026",
      "team@example.com",
      "a".repeat(200),
      "🙂 emoji team",
      "  padded  ",
    ];
    for (const name of names) {
      expect(operationKey("unit-create", "root", name), name).toMatch(SERVER_RULE);
    }
  });

  it("gives the same key for the same operation, which is what makes a retry safe", () => {
    //  The whole reason the key is derived rather than generated: a double-clicked button and a
    //  retried request are one operation, and must reuse one key.
    expect(operationKey("agent-create", "Invoice triage")).toBe(
      operationKey("agent-create", "Invoice triage"),
    );
  });

  it("gives different keys to names that differ only in a stripped character", () => {
    //  The reason this encodes rather than cleans. If "Sales EU" and "Sales-EU" folded to one
    //  key, the second create would be answered with the first's stored response — the person
    //  would be told their unit was created and shown somebody else's.
    expect(operationKey("unit-create", "root", "Sales EU")).not.toBe(
      operationKey("unit-create", "root", "Sales-EU"),
    );
    expect(operationKey("unit-create", "root", "Sales EU")).not.toBe(
      operationKey("unit-create", "root", "SalesEU"),
    );
  });

  it("keeps ids and versions readable, so a key still says what it was for", () => {
    expect(operationKey("agent-save", "0193c0de-1234-7890-abcd-ef0123456789", "v3")).toBe(
      "agent-save:0193c0de-1234-7890-abcd-ef0123456789:v3",
    );
  });

  it("distinguishes an absent value from an empty one", () => {
    //  "no parent" and "a parent whose id is the empty string" are different operations, and a
    //  gap that both produced would let one be answered with the other's result.
    expect(operationKey("unit-create", null, "Ops")).not.toBe(
      operationKey("unit-create", "", "Ops"),
    );
  });

  it("stays inside the server's length limit, and stays distinct when it truncates", () => {
    const long = "x".repeat(400);
    const first = operationKey("unit-create", "root", `${long}-alpha`);
    const second = operationKey("unit-create", "root", `${long}-omega`);

    expect(first.length).toBeLessThanOrEqual(200);
    expect(first).toMatch(SERVER_RULE);
    //  Differing only in the last five characters of a 400-character name: a plain truncation
    //  would give these the same key.
    expect(first).not.toBe(second);
  });
});

describe("a key that names a transition", () => {
  //  `updateProfile` keys on both the current values and the wanted ones. Keyed on the wanted ones
  //  alone, "set my zone to Dubai" is one operation for ever — so Dubai → Kolkata → Dubai replayed
  //  the first response and changed nothing. A browser test that ran twice found it.
  const key = (fromZone: string, toZone: string) =>
    operationKey("profile-update", "Pranav", "", fromZone, "Pranav", "", toZone);

  it("is the same key for a retry of the same change", () => {
    expect(key("Asia/Kolkata", "Asia/Dubai")).toBe(key("Asia/Kolkata", "Asia/Dubai"));
  });

  it("is a different key for the change back", () => {
    //  The property the profile route depends on: going back is not a retry of coming here.
    expect(key("Asia/Dubai", "Asia/Kolkata")).not.toBe(key("Asia/Kolkata", "Asia/Dubai"));
  });
});
