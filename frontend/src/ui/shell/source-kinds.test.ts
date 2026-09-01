/**
 * Every kind of source has a word for it, in both places one is shown.
 *
 * The Copilot panel and the search box both label a result by its `kind`, and both do it with a
 * dynamic key — `t(`kind.${source.kind}`)`. `messages.test.ts` cannot check those: it skips
 * dynamic keys, because their value is not knowable from the source. Its own header says that
 * shape is *"the most likely to hide one"*.
 *
 * So this checks the one case that matters. A seventh kind added to retrieval — a run, a task, a
 * skill — fails here rather than rendering `kind.run` at somebody in a side panel.
 */
import { describe, expect, it } from "vitest";

import { SOURCE_KINDS } from "@/lib/api/copilot";

import messages from "../../messages/en.json";

describe("source kind labels", () => {
  it.each(SOURCE_KINDS)("the Copilot panel has a word for %s", (kind) => {
    expect(messages.copilot.kind[kind]).toBeTruthy();
  });

  it.each(SOURCE_KINDS)("the search box has a word for %s", (kind) => {
    expect(messages.shell.searchKind[kind]).toBeTruthy();
  });
});
