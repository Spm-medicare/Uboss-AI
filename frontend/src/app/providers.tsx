"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api/errors";

/**
 * Server state for the whole application.
 *
 * The retry policy is the part worth reading. TanStack Query retries three times by default,
 * which is wrong for this product in two directions:
 *
 * - A 401, 403, 404 or 409 will never succeed on retry. Repeating it wastes the person's time
 *   and hides the real answer behind a spinner.
 * - A mutation must not be retried automatically at all. The client cannot know whether the
 *   first attempt was applied before the connection dropped, and a retry that the server does
 *   not recognise as a repeat is a duplicate command. Retrying is the caller's decision, made
 *   with the same idempotency key.
 */
function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && !error.retryable) return false;
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  // Created inside the component so each browser session gets its own cache. A module-level
  // client would be shared across requests during server rendering, which means one person's
  // data reaching another's page.
  const [queryClient] = useState(createQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
