/**
 * What this deployment can actually do at sign-in.
 *
 * Asked before the screen draws a single button. `PLAN.md`'s decision table promises *"managed
 * provider with MFA now"*, and each provider is optional — a deployment may have credentials for
 * none, one or all three. So the screen renders what the server says exists rather than a fixed
 * row of logos, two of which would fail on click.
 *
 * The same call reports whether email can be sent. A forgot-password screen that promised a link
 * on a system with no mail provider would be the plainest possible version of the rule this
 * codebase keeps repeating: never report success for something that did not happen.
 */

import { request } from "./client";
import type {
  ForgotPasswordAnswer,
  OAuthStart,
  SignInMethods,
} from "./contract";

export type Provider = {
  name: string;
  /** False when this deployment has no client id or secret for it. */
  configured: boolean;
};

export type Methods = {
  password: boolean;
  /** Every provider the product supports, in the order the screen shows them. */
  oauthProviders: Provider[];
  canSendEmail: boolean;
};

export async function fetchSignInMethods(signal?: AbortSignal): Promise<Methods> {
  const found = await request<SignInMethods>(
    "/auth/providers",
    signal ? { signal } : {},
  );
  return {
    password: found.password ?? true,
    oauthProviders: found.oauth_providers ?? [],
    canSendEmail: found.can_send_email,
  };
}

/**
 * Where to send the browser for a federated sign-in.
 *
 * The server mints the state and the PKCE challenge; neither the verifier nor anything derived
 * from it reaches this code. All the browser gets is a URL to navigate to.
 */
export async function startOAuth(
  provider: string,
  nextPath = "/dashboard",
): Promise<string> {
  const search = new URLSearchParams({ next_path: nextPath });
  const found = await request<OAuthStart>(
    `/auth/oauth/${provider}/start?${search.toString()}`,
  );
  return found.url;
}

export function finishOAuth(
  provider: string,
  code: string,
  state: string,
): Promise<Record<string, unknown>> {
  return request(`/auth/oauth/${provider}/callback`, {
    method: "POST",
    body: { code, state },
  });
}

export function requestPasswordReset(email: string): Promise<ForgotPasswordAnswer> {
  return request<ForgotPasswordAnswer>("/auth/password/forgot", {
    method: "POST",
    body: { email },
  });
}

export function resetPassword(
  token: string,
  password: string,
): Promise<{ status: string; email: string }> {
  return request("/auth/password/reset", {
    method: "POST",
    body: { token, password },
    //  Derived from the token, so a retry of the same reset reuses the key rather than minting a
    //  second one. The token is single-use anyway; this keeps the retry honest at both layers.
    idempotencyKey: `password-reset:${token.slice(0, 32)}`,
  });
}

export function acceptInvite(
  token: string,
  password: string,
  displayName?: string,
): Promise<{ status: string; email: string }> {
  return request("/auth/invite/accept", {
    method: "POST",
    body: {
      token,
      password,
      ...(displayName ? { display_name: displayName } : {}),
    },
    idempotencyKey: `invite-accept:${token.slice(0, 32)}`,
  });
}
