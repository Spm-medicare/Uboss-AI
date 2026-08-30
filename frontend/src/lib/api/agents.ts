/**
 * Agents, as the browser calls them.
 *
 * The same shape as `jobs.ts` on purpose: one save call for autosave and Save Draft, idempotency
 * keys derived from the version being written rather than generated per call, and the whole
 * record returned so the client's copy and the server's cannot drift.
 *
 * Two calls here have no equivalent in the other builders, and both come from `PLAN.md` §9:
 * `grantTool`, because *"tool suggestions never grant access"* and a save must not be able to,
 * and `saveTests`, because tests are a publish gate rather than a note.
 */

import { request } from "./client";
import type {
  AgentCreate,
  AgentList,
  AgentPublishSummary,
  AgentRead,
  AgentUpdate,
  AgentVersionList,
  AgentWorkbookLists,
  SandboxTestInput,
  SandboxTestList,
  ToolRead,
} from "./contract";

/** The agent with its collections filled in, so no call site has to write `?? []`. */
export type Agent = Omit<
  AgentRead,
  | "steps"
  | "skills"
  | "tools"
  | "io_schemas"
  | "knowledge_sources"
  | "escalation_rules"
  | "shares"
  | "situations_unanswered"
> & {
  steps: NonNullable<AgentRead["steps"]>;
  skills: NonNullable<AgentRead["skills"]>;
  tools: NonNullable<AgentRead["tools"]>;
  io_schemas: NonNullable<AgentRead["io_schemas"]>;
  knowledge_sources: NonNullable<AgentRead["knowledge_sources"]>;
  escalation_rules: NonNullable<AgentRead["escalation_rules"]>;
  shares: NonNullable<AgentRead["shares"]>;
  situations_unanswered: NonNullable<AgentRead["situations_unanswered"]>;
};

export type AgentLists = { [K in keyof AgentWorkbookLists]-?: NonNullable<AgentWorkbookLists[K]> };

function fill(agent: AgentRead): Agent {
  return {
    ...agent,
    steps: agent.steps ?? [],
    skills: agent.skills ?? [],
    tools: agent.tools ?? [],
    io_schemas: agent.io_schemas ?? [],
    knowledge_sources: agent.knowledge_sources ?? [],
    escalation_rules: agent.escalation_rules ?? [],
    shares: agent.shares ?? [],
    situations_unanswered: agent.situations_unanswered ?? [],
  };
}

export function fetchAgents(
  options: { status?: string; jobId?: string; signal?: AbortSignal } = {},
): Promise<AgentList> {
  const search = new URLSearchParams();
  if (options.status) search.set("status", options.status);
  if (options.jobId) search.set("job_id", options.jobId);
  const query = search.toString();
  return request<AgentList>(
    `/agents${query ? `?${query}` : ""}`,
    options.signal ? { signal: options.signal } : {},
  );
}

export async function fetchAgent(id: string, signal?: AbortSignal): Promise<Agent> {
  return fill(await request<AgentRead>(`/agents/${id}`, signal ? { signal } : {}));
}

export async function fetchAgentLists(signal?: AbortSignal): Promise<AgentLists> {
  const lists = await request<AgentWorkbookLists>(
    "/agents/lists",
    signal ? { signal } : {},
  );
  return {
    triggers: lists.triggers ?? [],
    frequencies: lists.frequencies ?? [],
    time_units: lists.time_units ?? [],
    approvals: lists.approvals ?? [],
    input_types: lists.input_types ?? [],
    output_formats: lists.output_formats ?? [],
    permissions: lists.permissions ?? [],
    locations: lists.locations ?? [],
    situations: lists.situations ?? [],
    visibility: lists.visibility ?? [],
  };
}

export function createAgent(body: AgentCreate): Promise<{ id: string; version: string }> {
  return request("/agents", {
    method: "POST",
    body,
    idempotencyKey: `agent-create:${body.name}`,
  });
}

export async function saveAgent(id: string, body: AgentUpdate): Promise<Agent> {
  return fill(
    await request<AgentRead>(`/agents/${id}`, {
      method: "PUT",
      body,
      idempotencyKey: `agent-save:${id}:v${body.expected_version}`,
      expectedVersion: body.expected_version,
    }),
  );
}

/**
 * Grant or withdraw one tool.
 *
 * A separate call because §9 says a suggestion never grants access, and a separate permission
 * because designing an agent and deciding what it may reach are different authorities.
 */
export function grantTool(
  agentId: string,
  toolId: string,
  granted: boolean,
  expectedVersion: number,
): Promise<ToolRead> {
  return request<ToolRead>(`/agents/${agentId}/tools/${toolId}/grant`, {
    method: "POST",
    body: { granted, expected_version: expectedVersion },
    idempotencyKey: `agent-tool:${agentId}:${toolId}:${granted}:v${expectedVersion}`,
    expectedVersion,
  });
}

// ---------------------------------------------------------------------- section C and publish

export function fetchTests(
  agentId: string,
  signal?: AbortSignal,
): Promise<SandboxTestList> {
  return request<SandboxTestList>(
    `/agents/${agentId}/tests`,
    signal ? { signal } : {},
  );
}

export function saveTests(
  agentId: string,
  tests: SandboxTestInput[],
  expectedVersion: number,
): Promise<SandboxTestList> {
  return request<SandboxTestList>(`/agents/${agentId}/tests`, {
    method: "PUT",
    body: { tests, expected_version: expectedVersion },
    idempotencyKey: `agent-tests:${agentId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export type AgentSummary = Omit<AgentPublishSummary, "warnings" | "gates"> & {
  warnings: { code: string; message: string }[];
  gates: { gate: string; name: string; passed: boolean; reason: string }[];
};

export async function fetchAgentPublishSummary(
  agentId: string,
  signal?: AbortSignal,
): Promise<AgentSummary> {
  const summary = await request<AgentPublishSummary>(
    `/agents/${agentId}/publish`,
    signal ? { signal } : {},
  );
  return {
    ...summary,
    warnings: summary.warnings ?? [],
    gates: summary.gates ?? [],
  };
}

export function submitAgent(
  agentId: string,
  expectedVersion: number,
): Promise<{ status: string; version: string }> {
  return request(`/agents/${agentId}/submit`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `agent-submit:${agentId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function withdrawAgent(
  agentId: string,
  expectedVersion: number,
): Promise<{ status: string; version: string }> {
  return request(`/agents/${agentId}/withdraw`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `agent-withdraw:${agentId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function publishAgent(
  agentId: string,
  expectedVersion: number,
): Promise<{ version_id: string; version_no: string }> {
  return request(`/agents/${agentId}/publish`, {
    method: "POST",
    body: { expected_version: expectedVersion },
    idempotencyKey: `agent-publish:${agentId}:v${expectedVersion}`,
    expectedVersion,
  });
}

export function fetchAgentVersions(
  agentId: string,
  signal?: AbortSignal,
): Promise<AgentVersionList> {
  return request<AgentVersionList>(
    `/agents/${agentId}/versions`,
    signal ? { signal } : {},
  );
}
