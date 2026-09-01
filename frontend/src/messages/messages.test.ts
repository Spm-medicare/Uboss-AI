/**
 * Every `t("…")` in the app resolves to a message that exists.
 *
 * This exists because a missing key is invisible until somebody opens the screen. TypeScript does
 * not know what `useTranslations("publish")` returns, ESLint has nothing to check it against, and
 * the build is happy — so `t("cannotSubmit")` against a namespace without that key compiles,
 * deploys, and then throws `MISSING_MESSAGE` in front of whoever reached that state first. It
 * happened twice in one afternoon, both times the same way: the key was added to the namespace of
 * the *screen* that renders the component, while the component reads its own.
 *
 * ## How it decides
 *
 * A file is scanned for `const <name> = useTranslations("<namespace>")`, which gives each
 * translator variable the namespaces it is bound to in that file. Every `<name>("key")` call is
 * then required to exist in at least one of them.
 *
 * "At least one" rather than "the right one" is deliberate. A file can bind the same variable name
 * in two components with different namespaces, and matching a call to its enclosing component needs
 * a parser rather than a regular expression. The looser rule still catches the whole class of bug
 * — a key that exists in *no* namespace the file uses — without ever failing a file that is
 * correct. A key present in both namespaces was going to render either way.
 *
 * Dynamic keys — `t(\`status.${x}\`)` — are skipped, because their value is not knowable here. They
 * are also the shape most likely to hide one, which is worth remembering rather than pretending
 * otherwise.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import messages from "./en.json";

const SRC = join(import.meta.dirname, "..");

/** Every .ts/.tsx under src, minus the tests and the generated contract. */
function sources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry === "node_modules") continue;
      sources(path, found);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) && entry !== "schema.d.ts") {
      found.push(path);
    }
  }
  return found;
}

/** `a.b.c` in the message tree, or undefined. */
function lookup(namespace: string, key: string): unknown {
  let node: unknown = messages;
  for (const part of `${namespace}.${key}`.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return node;
}

interface Missing {
  file: string;
  variable: string;
  key: string;
  namespaces: string[];
}

function scan(): Missing[] {
  const missing: Missing[] = [];

  for (const file of sources(SRC)) {
    const text = readFileSync(file, "utf8");

    //  variable -> the namespaces it is bound to anywhere in this file
    const bound = new Map<string, Set<string>>();
    for (const match of text.matchAll(
      /const\s+(\w+)\s*=\s*useTranslations\(\s*"([^"]+)"\s*\)/g,
    )) {
      const [, variable, namespace] = match;
      if (!variable || !namespace) continue;
      const set = bound.get(variable) ?? new Set<string>();
      set.add(namespace);
      bound.set(variable, set);
    }
    if (bound.size === 0) continue;

    for (const [variable, namespaces] of bound) {
      //  Only a literal key. A template literal is skipped — see the note above.
      const calls = new RegExp(`\\b${variable}\\(\\s*"([^"]+)"`, "g");
      for (const call of text.matchAll(calls)) {
        const key = call[1];
        if (!key) continue;
        const found = [...namespaces].some(
          (namespace) => lookup(namespace, key) !== undefined,
        );
        if (!found) {
          missing.push({
            file: file.slice(SRC.length + 1).replace(/\\/g, "/"),
            variable,
            key,
            namespaces: [...namespaces],
          });
        }
      }
    }
  }

  return missing;
}

describe("the message catalogue", () => {
  it("has a message for every key the app asks for", () => {
    const missing = scan();
    const report = missing.map(
      (row) => `${row.file}: ${row.variable}("${row.key}") — not in ${row.namespaces.join(", ")}`,
    );
    expect(report).toEqual([]);
  });

  it("is scanning something, so a passing run means something", () => {
    //  A regex that quietly stops matching would make the test above pass by finding nothing.
    //  This fails if the scan ever covers no files.
    expect(sources(SRC).length).toBeGreaterThan(50);
  });
});
