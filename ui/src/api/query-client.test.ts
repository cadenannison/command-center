import { describe, expect, it } from "vitest";
import { ApiError } from "./errors";
import { shouldRetry } from "./query-client";

describe("shouldRetry", () => {
  it("retries network and server errors twice, then stops", () => {
    expect(shouldRetry(0, new ApiError("network"))).toBe(true);
    expect(shouldRetry(1, new ApiError("server"))).toBe(true);
    expect(shouldRetry(2, new ApiError("server"))).toBe(false);
  });
  it("never retries a refusal, a validation error or a plain Error", () => {
    expect(shouldRetry(0, new ApiError("forbidden"))).toBe(false);
    expect(shouldRetry(0, new ApiError("validation"))).toBe(false);
    expect(shouldRetry(0, new Error("x"))).toBe(false);
  });
});
