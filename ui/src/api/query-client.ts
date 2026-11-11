import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./errors";

/** Retry only what may succeed on a second try (the app starting, a dropped request), at most twice. */
export function shouldRetry(failures: number, error: Error): boolean {
  return error instanceof ApiError && error.retryable && failures < 2;
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: shouldRetry } } });
}
