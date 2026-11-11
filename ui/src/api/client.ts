import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";
import { ApiError, toApiError } from "./errors";

/** The typed /v1 client. The base URL is the page's own origin, so every request is same-origin
 *  (decisions 0300, 0301): the app serves the page, and the dev server proxies /v1. It is never a
 *  configured or remote URL. No credential is set or read here; the loopback UI needs none, and
 *  nothing in the bundle may hold one (AGENTS.md rule 7). */
export function createApiClient(fetchImpl?: typeof fetch) {
  return createClient<paths>({
    baseUrl: globalThis.location.origin,
    credentials: "same-origin",
    ...(fetchImpl ? { fetch: fetchImpl } : {}),
  });
}

export type ApiClient = ReturnType<typeof createApiClient>;

export const api: ApiClient = createApiClient((input, init) => globalThis.fetch(input, init));

/** Run a client call and return its data, or throw an ApiError (never a raw Response or server text). */
export async function unwrap<T>(call: () => Promise<{ data?: T; response: Response }>): Promise<T> {
  let result: { data?: T; response: Response };
  try {
    result = await call();
  } catch (error) {
    throw toApiError(error);
  }
  if (!result.response.ok) throw toApiError(result.response);
  if (result.data === undefined) throw new ApiError("unknown", result.response.status);
  return result.data;
}
