/**
 * Signing in and knowing who is signed in.
 *
 * There is no token here, anywhere. The session is an http-only cookie the browser sends on its
 * own — this module never reads it, stores it, or puts it anywhere JavaScript can reach.
 */

import { request } from "./client";

export interface WorkspaceSummary {
  slug: string;
  name: string;
  display_name: string;
}

export interface CurrentUser {
  membership_id: string;
  display_name: string;
  email: string;
  job_title: string | null;
  roles: string[];
  /**
   * What this person may do. Menus use it to hide what is unusable.
   *
   * Never a permission check. The server re-resolves permissions on every route, because a list
   * sent to a browser is a list the browser can edit.
   */
  actions: string[];
  workspace_slug: string;
  workspace_name: string;
  timezone: string;
  org_node_id: string | null;
  stepped_up: boolean;
  session_expires_at: string;
}

export type SignInResult =
  | { status: "signed_in"; user: CurrentUser }
  | {
      status: "choose_workspace";
      challenge: string;
      workspaces: WorkspaceSummary[];
    };

export interface SignInInput {
  email: string;
  password: string;
}

export interface WorkspaceSelectionInput {
  challenge: string;
  workspace: string;
}

export interface StepUpResult {
  status: "stepped_up";
  method: "password";
  expires_at: string;
}

/**
 * Exchange an email and password for a session cookie.
 *
 * Two successful outcomes: signed in, or asked to pick a workspace. Neither is an error, so
 * neither throws — a caller has to handle both.
 *
 * Authentication uses rate limits and a purpose-built challenge, not stored response replay.
 * Email addresses and passwords must never become idempotency keys or replay records.
 */
export function signIn(input: SignInInput): Promise<SignInResult> {
  return request<SignInResult>("/auth/sign-in", {
    method: "POST",
    body: input,
    idempotencyKey: null,
  });
}

export function selectWorkspace(
  input: WorkspaceSelectionInput,
): Promise<Extract<SignInResult, { status: "signed_in" }>> {
  return request<Extract<SignInResult, { status: "signed_in" }>>(
    "/auth/select-workspace",
    {
      method: "POST",
      body: input,
      idempotencyKey: null,
    },
  );
}

export function signOut(): Promise<void> {
  return request<void>("/auth/sign-out", {
    method: "POST",
    idempotencyKey: "sign-out",
  });
}

/** Open a short high-risk-action window for the current session only. */
export function stepUpWithPassword(password: string): Promise<StepUpResult> {
  return request<StepUpResult>("/auth/step-up/password", {
    method: "POST",
    body: { password },
    // Credential payloads are never persisted in generic idempotency replay storage.
    idempotencyKey: null,
  });
}

/** Who is signed in. Throws `ApiError` with status 401 when nobody is. */
export function fetchCurrentUser(signal?: AbortSignal): Promise<CurrentUser> {
  return request<CurrentUser>("/auth/me", signal ? { signal } : {});
}

/** True when the signed-in person holds this action anywhere in their workspace. */
export function can(user: CurrentUser | undefined, action: string): boolean {
  return user?.actions.includes(action) ?? false;
}
