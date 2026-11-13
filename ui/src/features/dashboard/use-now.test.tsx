import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NOW_TICK_MS, useNow } from "./use-now";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 10, 12, 23, 59).getTime());
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useNow", () => {
  it("starts at the current time and moves on every minute", () => {
    const { result } = renderHook(() => useNow());
    const first = result.current;
    expect(first).toBe(new Date(2026, 10, 12, 23, 59).getTime());
    act(() => {
      vi.advanceTimersByTime(NOW_TICK_MS);
    });
    expect(new Date(result.current).getDate()).toBe(13);
    expect(result.current).toBeGreaterThan(first);
  });

  it("stops its timer on unmount", () => {
    const { unmount } = renderHook(() => useNow());
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
