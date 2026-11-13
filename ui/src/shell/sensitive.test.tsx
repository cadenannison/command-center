import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventsWidget } from "../features/dashboard/events-widget";
import { SummaryCard } from "../features/dashboard/summary-card";
import { json } from "../features/dashboard/test-support";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("privacy mask marks", () => {
  it("marks an event title and location, not its time", async () => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start.getTime() + 86_400_000);
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          json([
            {
              id: "e1",
              kind: "event",
              source: "apple_calendar",
              title: "Dentist with Dr Lee",
              start: start.toISOString(),
              end: end.toISOString(),
              due: null,
              status: null,
              urgency: 0,
              priority: null,
              fetched_at: "2026-11-12T10:00:00Z",
              has_note: false,
              user_id: "local",
              raw: { location: "Room 4" },
            },
          ]),
        ),
      ),
    );
    wrap(<EventsWidget title="Events" source="cal" status="Calendar" widthTier={3} heightTier={3} />);
    const row = await screen.findByTestId("event-row");
    expect(screen.getByText("Dentist with Dr Lee")).toHaveAttribute("data-sensitive");
    expect(screen.getByText("Room 4")).toHaveAttribute("data-sensitive");
    const time = row.querySelector(".tnum");
    expect(time).not.toHaveAttribute("data-sensitive");
    // Purely visual: the text is still in the DOM.
    expect(row).toHaveTextContent("Dentist with Dr Lee");
  });

  it("marks the summary headline and its entries", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          json({
            summary: { headline: "Call Sam about rent", priorities: ["Email Priya"], heads_up: ["Quiz Friday"] },
            provider: "gemini",
            cached: false,
          }),
        ),
      ),
    );
    wrap(<SummaryCard cols={12} />);
    expect(await screen.findByText("Call Sam about rent")).toHaveAttribute("data-sensitive");
    expect(screen.getByText("Email Priya")).toHaveAttribute("data-sensitive");
    expect(screen.getByText("Quiz Friday")).toHaveAttribute("data-sensitive");
  });
});
