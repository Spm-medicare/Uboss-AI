"use client";

/**
 * The signed-in person, as React sees them.
 *
 * One query, cached under one key, so every component asks the same question and gets the same
 * answer. Signing in or out invalidates it rather than writing to it, which keeps the server as
 * the only place that decides who is signed in.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import {
  fetchCurrentUser,
  selectWorkspace as selectWorkspaceRequest,
  signIn as signInRequest,
  signOut as signOutRequest,
  type CurrentUser,
  type SignInInput,
  type SignInResult,
  type WorkspaceSelectionInput,
} from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";

export const SESSION_QUERY_KEY = ["session"] as const;

export interface SessionState {
  user: CurrentUser | undefined;
  /** True until the first answer arrives. Distinct from "signed out". */
  isLoading: boolean;
  /** The server said nobody is signed in. A fact, not a failure. */
  isSignedOut: boolean;
  /**
   * Something went wrong that is *not* "signed out" — the API is down, or it failed. Kept
   * separate so the interface can say "we could not reach UBOSS" instead of bouncing someone
   * to a sign-in form that will not work either.
   */
  error: Error | null;
}

export function useSession(): SessionState {
  const query = useQuery({
    queryKey: SESSION_QUERY_KEY,
    queryFn: ({ signal }) => fetchCurrentUser(signal),
    // A 401 here is the answer, not a fault: retrying it would delay the sign-in screen for
    // every signed-out visitor.
    retry: false,
    staleTime: 60_000,
  });

  const unauthenticated =
    query.error instanceof ApiError && query.error.isUnauthenticated;

  return {
    user: query.data,
    isLoading: query.isPending,
    isSignedOut: unauthenticated,
    error: unauthenticated ? null : query.error,
  };
}

export function useSignIn(): UseMutationResult<SignInResult, Error, SignInInput> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: signInRequest,
    onSuccess: async (result) => {
      if (result.status === "signed_in") {
        // Seed the cache from the response so the next screen does not flash a loading state
        // for data the sign-in already returned.
        queryClient.setQueryData(SESSION_QUERY_KEY, result.user);
      }
    },
  });
}

export function useSelectWorkspace(): UseMutationResult<
  Extract<SignInResult, { status: "signed_in" }>,
  Error,
  WorkspaceSelectionInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: selectWorkspaceRequest,
    onSuccess: async (result) => {
      queryClient.setQueryData(SESSION_QUERY_KEY, result.user);
    },
  });
}

export function useSignOut(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: signOutRequest,
    onSettled: async () => {
      // Cleared whether or not the request succeeded. If the server did not hear us, the local
      // cache still must not go on showing a session the person asked to end.
      queryClient.clear();
    },
  });
}
