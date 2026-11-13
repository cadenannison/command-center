import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json } from "./test-support";
import { useEvents } from "./use-events";

afterEach(() => {
  vi.unstubAllGlobals();
});

const evt = (id: string) => ({
  id,
  kind: "event",
  source: "apple_calendar",
  title: id,
  start: "2026-11-12T16:00:00Z",
  end: null,
  due: null,
  status: null,
  urgency: 0,
  priority: null,
  fetched_at: "2026-11-12T10:00:00Z",
  has_note: false,
  user_id: "local",
});

describe("useEvents when the date window changes (midnight)", () => {
  it.each(["events", "week", "weather"] as const)("keeps the %s data on screen while the next window loads", async (name) => {
    let release: (() => void) | undefined;
    const fetchMock = vi.fn(async (request: Request) => {
      const from = new URL(request.url).searchParams.get("from");
      if (from === "2") await new Promise<void>((resolve) => (release = resolve));
      return json([evt(from === "2" ? "next-day" : "first-day")]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result, rerender } = renderHook(({ from }) => useEvents(from, "9", name), { wrapper, initialProps: { from: "1" } });
    await waitFor(() => {
      expect(result.current.data?.[0]?.id).toBe("first-day");
    });
    rerender({ from: "2" });
    expect(result.current.isPending).toBe(false);
    expect(result.current.isError).toBe(false);
    expect(result.current.data?.[0]?.id).toBe("first-day");
    expect(result.current.isPlaceholderData).toBe(true);
    release?.();
    await waitFor(() => {
      expect(result.current.data?.[0]?.id).toBe("next-day");
    });
    expect(result.current.isPlaceholderData).toBe(false);
  });
});
