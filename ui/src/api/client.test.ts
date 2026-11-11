import { describe, expect, it, vi } from "vitest";
import { createApiClient, unwrap } from "./client";
import { ApiError, kindForStatus, toApiError } from "./errors";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("error mapping", () => {
  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [422, "validation"],
    [429, "rate_limited"],
    [500, "server"],
    [503, "server"],
    [418, "unknown"],
  ] as const)("maps status %i to %s", (status, kind) => {
    expect(kindForStatus(status)).toBe(kind);
    expect(toApiError(new Response(null, { status })).kind).toBe(kind);
  });

  it("maps a fetch failure to network and anything else to unknown", () => {
    expect(toApiError(new TypeError("Failed to fetch")).kind).toBe("network");
    expect(toApiError("boom").kind).toBe("unknown");
  });

  it("only network and server errors are retryable", () => {
    expect(new ApiError("network").retryable).toBe(true);
    expect(new ApiError("server").retryable).toBe(true);
    expect(new ApiError("validation").retryable).toBe(false);
    expect(new ApiError("forbidden").retryable).toBe(false);
  });
});

describe("unwrap", () => {
  it("never echoes server text in an error", async () => {
    const client = createApiClient(
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "secret-looking text fake-123" }, 500))),
    );
    const error = await unwrap(() => client.GET("/v1/health")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("server");
    expect((error as ApiError).message).not.toContain("fake-123");
  });

  it("turns a thrown network failure into an ApiError", async () => {
    const client = createApiClient(vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(unwrap(() => client.GET("/v1/health"))).rejects.toMatchObject({ kind: "network" });
  });

  it("returns the body of a success", async () => {
    const client = createApiClient(vi.fn(() => Promise.resolve(jsonResponse({ status: "ok" }))));
    await expect(unwrap(() => client.GET("/v1/health"))).resolves.toEqual({ status: "ok" });
  });
});

describe("client", () => {
  it("calls a same-origin relative /v1 path and sends no authorization header", async () => {
    const fetchMock = vi.fn<(req: Request) => Promise<Response>>(() => Promise.resolve(jsonResponse([])));
    const client = createApiClient(fetchMock as unknown as typeof fetch);
    await client.GET("/v1/agenda/{period}", { params: { path: { period: "day" }, query: { date: "2026-11-11" } } });
    const request = fetchMock.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    const url = new URL(request?.url ?? "");
    expect(url.origin).toBe(globalThis.location.origin);
    expect(url.pathname).toBe("/v1/agenda/day");
    expect(url.searchParams.get("date")).toBe("2026-11-11");
    expect(request?.headers.get("authorization")).toBeNull();
    expect(request?.credentials).toBe("same-origin");
  });
});
