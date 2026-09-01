/**
 * Signing in and knowing who is signed in.
 *
 * There is no token here, anywhere. The session is an http-only cookie the browser sends on its
 * own — this module never reads it, stores it, or puts it anywhere JavaScript can reach.
 *
 * **Every type comes from the generated contract.** They used to be written by hand here, which
 * meant the compiler was checking against whatever the frontend believed rather than what the
 * server publishes. A renamed field would have type-checked cleanly and failed at runtime.
 */

import type {
  ChooseWorkspaceResponse,
  CurrentUser,
  PasswordStepUpRequest,
  SessionSummary,
  SignInRequest,
  SignInResponse,
  StepUpResponse,
  WorkspaceSelectionRequest,
  WorkspaceSummary,
} from "./contract";
import { request } from "./client";
import { operationKey } from "./idempotency";

export type {
  ChooseWorkspaceResponse,
  CurrentUser,
  SignInResponse,
  StepUpResponse,
  WorkspaceSummary,
};

/**
 * Sign-in has two successful outcomes, and neither is an error.
 *
 * The server answers 200 with one or the other, so a caller has to handle both — a union rather
 * than an optional field, so the compiler makes sure it does.
 */
export type SignInResult = SignInResponse | ChooseWorkspaceResponse;

export type SignInInput = SignInRequest;
export type WorkspaceSelectionInput = WorkspaceSelectionRequest;
export type StepUpInput = PasswordStepUpRequest;
export type StepUpResult = StepUpResponse;

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

/**
 * Change your own name, job title or timezone — §13's *"Profile and timezone/locale"*.
 *
 * The timezone is the one that matters most: `CurrentUser.timezone` is what every screen formats
 * instants with, and until `PATCH /auth/me` existed nothing wrote it, so a person outside the
 * workspace's zone read every time in the wrong one.
 *
 * ## The key names the transition, not the destination
 *
 * `from` is not decoration. Keyed on the new values alone, *"set my zone to Dubai"* is one
 * operation for ever — so somebody who set Dubai, went back to Kolkata, and set Dubai again was
 * handed the first response as a replay and nothing changed. The idempotency store was doing
 * exactly what it is for; the key was wrong.
 *
 * Keyed on both ends, a retry of the same transition still replays — which is the point — and a
 * return trip is a different operation, because it is one. Found by a browser test that ran twice.
 */
export function updateProfile(
  input: {
    display_name?: string;
    job_title?: string | null;
    timezone?: string;
  },
  from: Pick<CurrentUser, "display_name" | "job_title" | "timezone">,
): Promise<CurrentUser> {
  return request<CurrentUser>("/auth/me", {
    method: "PATCH",
    body: input,
    idempotencyKey: operationKey(
      "profile-update",
      from.display_name,
      from.job_title ?? "",
      from.timezone,
      input.display_name ?? "",
      input.job_title ?? "",
      input.timezone ?? "",
    ),
  });
}

/** Where this account is signed in — §13's *"Security, MFA and sessions"*. */
export function fetchSessions(signal?: AbortSignal): Promise<SessionSummary[]> {
  return request<SessionSummary[]>("/auth/sessions", signal ? { signal } : {});
}

/**
 * End one of them.
 *
 * Ending the current one signs this browser out, which the screen says before offering it — a
 * person clearing old sessions should not be surprised by being logged out of the one they are
 * using.
 */
export function revokeSession(id: string): Promise<void> {
  return request(`/auth/sessions/${id}`, {
    method: "DELETE",
    idempotencyKey: operationKey("session-revoke", id),
  });
}
