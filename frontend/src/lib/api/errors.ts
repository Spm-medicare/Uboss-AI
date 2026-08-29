/**
 * The API's error envelope, as the browser sees it.
 *
 * The backend returns exactly this shape for every failure (PLAN section 28), so the UI can
 * decide what to do without reading prose:
 *
 * - `code` is stable. Branch on it.
 * - `message` is safe to show a person. Show it.
 * - `fieldErrors` go next to the input that caused them, so nothing the person typed is lost.
 * - `correlationId` is what support asks for.
 * - `retryable` says whether offering "Try again" is honest. Never guess this — offering a retry
 *   on a command that already took effect is how duplicates get created.
 */

export interface ApiFieldError {
  field: string;
  code: string;
  message: string;
}

interface ApiErrorEnvelope {
  code: string;
  message: string;
  field_errors: ApiFieldError[];
  correlation_id: string;
  retryable: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: ApiFieldError[];
  readonly correlationId: string;
  readonly retryable: boolean;

  constructor(status: number, envelope: ApiErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.status = status;
    this.code = envelope.code;
    this.fieldErrors = envelope.field_errors ?? [];
    this.correlationId = envelope.correlation_id ?? "";
    this.retryable = envelope.retryable ?? false;
  }

  /** The person is signed out, or their session expired. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** The person is known but not permitted. A distinct screen state, not a toast. */
  get isDenied(): boolean {
    return this.status === 403;
  }

  /** Someone else changed the record first. The form must re-read before saving again. */
  get isConflict(): boolean {
    return this.status === 409;
  }

  /** Per-field messages a form can place. */
  errorFor(field: string): string | undefined {
    return this.fieldErrors.find((e) => e.field === field)?.message;
  }
}

/**
 * When the request never reached the API at all — the network is down, DNS failed, the browser
 * is offline.
 *
 * Kept separate from `ApiError` because the honest wording differs: "we could not reach UBOSS"
 * is true here and false when the server answered with a refusal.
 */
export class NetworkError extends Error {
  readonly retryable = true;

  constructor(cause?: unknown) {
    super("Could not reach UBOSS. Check your connection and try again.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

const FALLBACK: ApiErrorEnvelope = {
  code: "unexpected_response",
  message: "The server returned something we could not read. Nothing was changed.",
  field_errors: [],
  correlation_id: "",
  retryable: false,
};

/**
 * Turn a failed response into an `ApiError`.
 *
 * A body that is not the expected envelope — an HTML error page from a proxy, an empty 502 —
 * still becomes a real error. It is never treated as a success with no data, because a screen
 * that renders an empty state on a failed request tells the person their data is gone.
 */
export async function toApiError(response: Response): Promise<ApiError> {
  let envelope = FALLBACK;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "code" in body && "message" in body) {
      envelope = body as ApiErrorEnvelope;
    }
  } catch {
    /* Not JSON. The fallback above is already correct. */
  }
  return new ApiError(response.status, envelope);
}
