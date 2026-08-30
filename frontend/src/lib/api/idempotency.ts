/**
 * Building an `Idempotency-Key` out of what a person typed.
 *
 * The key names the *logical operation*, so a retry of the same click reuses it — that is the
 * whole rule, and `CLAUDE.md` states it: *"Idempotency keys are derived from the logical
 * operation, never `crypto.randomUUID()` per call."* For a create, the operation is identified by
 * what is being created: the parent and the name, the agent's name, the objective's title.
 *
 * Which meant free text went straight into the header — and the server's alphabet is
 * `[A-Za-z0-9][A-Za-z0-9._:-]{7,199}`. Creating a company called **"UBOSS Demo"** produced
 * `unit-create:root:UBOSS Demo`, the space was refused, and the person got *"Idempotency-Key is
 * not valid"* for having put a space in a name. Every create in the product had this fault; a
 * one-word name happened to work, which is why it survived.
 *
 * ## Why encoding rather than stripping
 *
 * Folding the disallowed characters away — `"Sales EU"` and `"Sales-EU"` both to `sales-eu` —
 * would make two different creates share a key. The second would then be answered with the
 * first's stored response: the person would be told their new unit was created, and shown the
 * other one. A silent wrong answer is far worse than the error this replaces.
 *
 * So the text is **encoded**, not cleaned. base64url is exactly the alphabet the server allows
 * (`A-Za-z0-9-_`), and it is reversible, so two distinct names cannot collide.
 */

/** The server's own rule, from `backend/src/uboss/core/idempotency.py`. */
const MAX_LENGTH = 200;

/** Characters that need no encoding. A subset of the server's alphabet, minus the `:` separator. */
const ALREADY_SAFE = /^[A-Za-z0-9._-]+$/;

/**
 * base64url of a string's UTF-8 bytes.
 *
 * Via `TextEncoder` rather than `btoa(value)` directly: `btoa` throws on any character above
 * U+00FF, so a workspace called "Bäcker" or "東京支社" would crash the call that was meant to make
 * the name safe.
 */
function encode(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * A short, stable digest — used only to keep a very long key inside the server's limit.
 *
 * FNV-1a, 32 bits. Not a security primitive and not used as one: it is a tiebreaker on values
 * that already share a long encoded prefix, and its only job is to stop a truncation from
 * merging two names that differ near the end. `crypto.subtle.digest` would be stronger and is
 * asynchronous, which would make every key builder in the codebase async for a case that needs
 * a name over ~110 characters to occur at all.
 */
function digest(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    //  The FNV prime, via shifts — `hash * 16777619` overflows a double's integer range and
    //  starts losing low bits, which is where a hand-written FNV usually goes wrong.
    hash = (hash + (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24)) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

/**
 * Build a key from a prefix and the values that identify the operation.
 *
 * Values that are already in the safe alphabet — ids, version numbers, dates, enum members —
 * pass through readable, so a key in a log still says what it was for. Anything else is encoded.
 *
 *     operationKey("unit-create", parentId ?? "root", name)
 *     // → "unit-create:root:VUJPU1MgRGVtbw"
 *
 * `null` and `undefined` become the literal `none`, so "no parent" is a stated value rather than
 * a gap that two different operations could both produce.
 */
export function operationKey(
  prefix: string,
  ...parts: readonly (string | number | null | undefined)[]
): string {
  const encoded = parts.map((part) => {
    if (part === null || part === undefined) return "none";
    const text = String(part);
    if (text === "") return "empty";
    return ALREADY_SAFE.test(text) ? text : encode(text);
  });

  const key = [prefix, ...encoded].join(":");
  if (key.length <= MAX_LENGTH) return key;

  //  Too long for the header. Keep the readable head and end with a digest of the whole thing,
  //  so the key stays deterministic and two long names that differ anywhere still differ here.
  const suffix = `:${digest(key)}`;
  return key.slice(0, MAX_LENGTH - suffix.length) + suffix;
}
