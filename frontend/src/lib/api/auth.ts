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
  SignInRequest,
  SignInResponse,
  StepUpResponse,
  WorkspaceSelectionRequest,
  WorkspaceSummary,
} from "./contract";
import { request } from "./client";

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
