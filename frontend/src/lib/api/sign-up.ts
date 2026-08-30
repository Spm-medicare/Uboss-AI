/**
 * Creating an account and its workspace.
 *
 * One call, because the two are one decision: an account with no workspace cannot do anything,
 * and a workspace with no member cannot be reached. The server does both inside a single
 * `SECURITY DEFINER` function, so a half-created sign-up is not a state that exists.
 *
 * The response is a session — the same `SignInResponse` the password path returns — because the
 * person just proved they own the password by choosing it. There is no "check your inbox" step
 * in front of it; when mail is configured, verification belongs after the first sign-in, not as
 * a wall in front of an account that has nothing in it yet.
 */

import { request } from "./client";
import { operationKey } from "./idempotency";
import type { SignInResponse } from "./contract";

export interface SignUpInput {
  display_name: string;
  email: string;
  workspace_name: string;
  password: string;
}

export function signUp(input: SignUpInput): Promise<SignInResponse> {
  return request<SignInResponse>("/auth/sign-up", {
    method: "POST",
    body: input,
    //  Keyed on the address, not on a fresh uuid. A double-clicked button or a retried request
    //  is the *same* sign-up, and reusing the key is what stops it becoming a second workspace
    //  the person never asked for.
    //
    //  `@` and `+` are outside the key alphabet the server accepts, so they are folded rather
    //  than passed through. Folding keeps the key deterministic, which is the whole point — a
    //  key the server rejects turns every retry into a fresh request.
    idempotencyKey: operationKey("sign-up", input.email.trim().toLowerCase()),
  });
}
