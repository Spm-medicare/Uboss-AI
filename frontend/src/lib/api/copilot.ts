/**
 * The Copilot and the search box — §12, as the browser calls them.
 *
 * **There is no `applyCopilotChange`.** A proposal is carried out by the person, on the object's
 * own screen, through the same route and the same permission check as any other edit. The backend
 * has no route to apply one; neither does this, and a test on the published contract fails if one
 * ever appears.
 *
 * `ask` is a POST that deliberately passes `idempotencyKey: null`. The client refuses a mutation
 * without a key, and rightly — but this one writes nothing except an audit row saying somebody
 * asked. Two identical questions ten seconds apart are two questions, and collapsing them would
 * lose the second. It is a POST rather than a GET because a question is a person's own words, and
 * a GET puts those in the access log, the proxy log and the browser history.
 */

import { request } from "./client";
import type { CopilotAnswer, CopilotSource } from "./contract";

export async function askCopilot(
  question: string,
  signal?: AbortSignal,
): Promise<CopilotAnswer> {
  return request<CopilotAnswer>("/copilot/ask", {
    method: "POST",
    body: { question },
    idempotencyKey: null,
    ...(signal ? { signal } : {}),
  });
}

export async function searchWorkspace(
  q: string,
  signal?: AbortSignal,
): Promise<CopilotSource[]> {
  return request<CopilotSource[]>(`/copilot/search?q=${encodeURIComponent(q)}`, {
    ...(signal ? { signal } : {}),
  });
}

/**
 * Every kind of object retrieval can return.
 *
 * Mirrors the six blocks of `backend/src/uboss/modules/copilot/retrieval.py`. A list in a second
 * language is a list that can drift, so it is not trusted to stay right by being written down:
 * `source-kinds.test.ts` asserts each one has a label in both the Copilot panel's namespace and
 * the search box's, which is where a missing kind would show up as a raw message key.
 */
export const SOURCE_KINDS = [
  "objective",
  "job",
  "agent",
  "supervisor",
  "org_unit",
  "position",
] as const;
