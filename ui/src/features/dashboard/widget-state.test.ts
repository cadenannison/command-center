import { describe, expect, it } from "vitest";
import { deriveQueryState, type QuerySnapshot } from "./widget-state";

const base: QuerySnapshot = { hasData: true, isPending: false, isError: false, dataUpdatedAt: 0, isEmpty: false };

describe("deriveQueryState", () => {
  it("is loading while the first request is out", () => {
    expect(deriveQueryState({ ...base, hasData: false, isPending: true })).toEqual({ kind: "loading" });
  });

  it("is an error when the request failed and there is nothing to show", () => {
    expect(deriveQueryState({ ...base, hasData: false, isPending: false, isError: true })).toEqual({ kind: "error" });
    expect(deriveQueryState({ ...base, hasData: false, isPending: true, isError: true })).toEqual({ kind: "error" });
  });

  it("is stale, with the last good time, when a refresh failed but data exists", () => {
    const at = new Date(2026, 10, 12, 15, 5).getTime();
    expect(deriveQueryState({ ...base, isError: true, dataUpdatedAt: at })).toEqual({ kind: "stale", lastSynced: "3:05 PM" });
  });

  it("is empty or ready by what the data holds", () => {
    expect(deriveQueryState({ ...base, isEmpty: true })).toEqual({ kind: "empty" });
    expect(deriveQueryState(base)).toEqual({ kind: "ready" });
  });
});
