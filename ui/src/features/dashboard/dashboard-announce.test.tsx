import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_LAYOUTS } from "../../layout";
import { DashboardView } from "./dashboard-view";
import { dashboardOf, installGridEnv, json } from "./test-support";

// Decision 0388: a delayed announcement ("Added ...") must never overwrite a newer one ("Undone."). The old test relied on
// the click-to-click gap being longer than the 100 ms delay, which failed under load. This one waits past the delay on purpose.
const DELAY_PASSED_MS = 250;

beforeEach(() => {
  installGridEnv(1200, 1400);
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(json([]))),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DashboardView dashboard={dashboardOf("main", "Main", 1, DEFAULT_LAYOUTS.minimal)} flushRef={createRef()} onConflict={() => Promise.resolve(true)} />
    </QueryClientProvider>,
  );
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

describe("delayed announcements", () => {
  it("drops the pending 'Added' announcement when Undo announces first, however late the timer would have fired", async () => {
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    await user.click(await screen.findByRole("button", { name: "Add Weather" }));
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await sleep(DELAY_PASSED_MS);
    expect(screen.getByTestId("live-region")).toHaveTextContent("Undone.");
    expect(screen.getByTestId("live-region")).not.toHaveTextContent("Added Weather");
  });

  it("still announces 'Added' when nothing else is announced after it", async () => {
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    await user.click(await screen.findByRole("button", { name: "Add Weather" }));
    await waitFor(() => {
      expect(screen.getByTestId("live-region")).toHaveTextContent("Added Weather at column 1, row 11, 4 wide, 8 tall.");
    });
  });
});
