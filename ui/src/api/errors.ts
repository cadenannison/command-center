/** What went wrong, in terms the UI can act on. The message is fixed text: it never carries the server's
 *  `detail` or any request data (a 422 body, a URL, a header), so nothing sensitive can reach the page. */
export type ApiErrorKind =
  | "network"
  | "validation"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "rate_limited"
  | "server"
  | "unknown";

const MESSAGES: Record<ApiErrorKind, string> = {
  network: "Could not reach the app. Check that it is running.",
  validation: "The request was not accepted.",
  unauthorized: "Not signed in to the app.",
  forbidden: "This is not allowed from here.",
  not_found: "Not found.",
  rate_limited: "Too many requests. Try again in a minute.",
  server: "The app had a problem. Try again.",
  unknown: "Something went wrong.",
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, status: number | null = null) {
    super(MESSAGES[kind]);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }

  /** Worth another automatic attempt: the app may be starting, or a request may have been dropped. */
  get retryable(): boolean {
    return this.kind === "network" || this.kind === "server";
  }
}

export function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 422) return "validation";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "unknown";
}

/** Map anything a client call can throw or return to an ApiError. A fetch failure is a TypeError. */
export function toApiError(source: unknown): ApiError {
  if (source instanceof ApiError) return source;
  if (source instanceof Response) return new ApiError(kindForStatus(source.status), source.status);
  if (source instanceof TypeError) return new ApiError("network");
  return new ApiError("unknown");
}
