import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/toast";
import { json } from "../dashboard/test-support";
import { HistoryPage } from "./history-page";
import { at, entry, NOW } from "./history-test-support";
import type { HistoryDay } from "./use-history";

// Only Date is faked, so timers and promises still run. Thursday, Nov 12, 2026, 3:30 PM Denver.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const DAYS: HistoryDay[] = [
  {
    day: "2026-11-10",
    done_by_you: [entry("old", "done_by_you", at(10, 9), { title: "Old essay" })],
    gone: [entry("vanished", "gone", at(10, 12), { title: "Vanished event" })],
  },
  {
    day: "2026-11-12",
    done_by_you: [entry("mine", "done_by_you", at(12, 9), { title: "Lab report", note: "turned in late" })],
    done_by_source: [entry("theirs", "done_by_source", at(12, 11), { title: "Quiz" })],
    dismissed: [entry("noise", "dismissed", at(12, 13), { title: "Newsletter" })],
  },
];

interface Server {
  readonly calls: { method: string; path: string; query: string }[];
  days: HistoryDay[];
  failHistory: boolean;
}

function mount(days: HistoryDay[] = DAYS, failHistory = false) {
  const server: Server = { calls: [], days, failHistory };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: Request) => {
      const url = new URL(input.url);
      server.calls.push({ method: input.method, path: url.pathname, query: url.search });
      if (url.pathname === "/v1/history") {
        return Promise.resolve(server.failHistory ? json({ detail: "secret server text" }, 500) : json(server.days));
      }
      if (url.pathname.endsWith("/restore")) {
        // The restored entry leaves the ledger, as it does on the server.
        server.days = server.days.map((d) => ({
          ...d,
          done_by_you: (d.done_by_you ?? []).filter((e) => !url.pathname.includes(`/${e.item_id}/`)),
          dismissed: (d.dismissed ?? []).filter((e) => !url.pathname.includes(`/${e.item_id}/`)),
        }));
        return Promise.resolve(json({ id: "x" }));
      }
      return Promise.resolve(json({ detail: "unexpected" }, 404));
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <main>
        <ToastProvider>
          <HistoryPage />
        </ToastProvider>
      </main>
    </QueryClientProvider>,
  );
  return { server, client };
}

const titles = () => screen.getAllByTestId("history-entry").map((li) => within(li).getAllByText(/./)[0]?.textContent);

describe("HistoryPage", () => {
  it("shows loading, then days newest first with a heading and counts", async () => {
    const { server } = mount();
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Thursday, Nov 12" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "History" })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Thursday, Nov 12", "Tuesday, Nov 10"]);
    const days = screen.getAllByTestId("history-day");
    expect(days[0]).toHaveTextContent("2 done, 1 dismissed");
    expect(days[1]).toHaveTextContent("1 done, 0 dismissed");
    expect(server.calls[0]).toMatchObject({ path: "/v1/history", query: "?from=2026-10-14&to=2026-11-12" });
  });

  it("shows title, outcome and time on each entry, and the note", async () => {
    mount();
    await screen.findByText("Lab report");
    const first = screen.getAllByTestId("history-entry")[0];
    expect(first).toHaveTextContent("Newsletter");
    expect(first).toHaveTextContent("Dismissed");
    expect(first).toHaveTextContent("1:00 PM");
    expect(screen.getByText("turned in late")).toBeInTheDocument();
    expect(screen.getByText("Vanished event").closest("li")).toHaveTextContent("Gone");
  });

  it("marks titles and notes data-sensitive", async () => {
    mount();
    expect((await screen.findByText("Lab report")).closest("[data-sensitive]")).not.toBeNull();
    expect(screen.getByText("turned in late").closest("[data-sensitive]")).not.toBeNull();
  });

  it("filters All, Done and Dismissed", async () => {
    mount();
    const user = userEvent.setup();
    await screen.findByText("Lab report");
    expect(screen.getByRole("radio", { name: "All" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Dismissed" }));
    expect(titles()).toEqual(["Newsletter"]);
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
    await user.click(screen.getByRole("radio", { name: "Done" }));
    expect(titles()).toEqual(["Quiz", "Lab report", "Old essay"]);
    await user.click(screen.getByRole("radio", { name: "All" }));
    expect(screen.getAllByTestId("history-entry")).toHaveLength(5);
  });

  it("searches the loaded entries without another request", async () => {
    const { server } = mount();
    const user = userEvent.setup();
    await screen.findByText("Lab report");
    const calls = server.calls.length;
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "late");
    expect(titles()).toEqual(["Lab report"]);
    await user.clear(screen.getByRole("searchbox", { name: "Search" }));
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "nothing like this");
    expect(screen.getByText("Nothing matches.")).toBeInTheDocument();
    expect(server.calls).toHaveLength(calls);
  });

  it("offers Restore on today's done-by-you and dismissed entries only", async () => {
    mount();
    await screen.findByText("Lab report");
    const rows = screen.getAllByTestId("history-entry");
    const has = (title: string) =>
      rows
        .filter((r) => r.textContent.includes(title))
        .some((r) => within(r).queryByRole("button", { name: /^Restore/ }) !== null);
    expect(has("Newsletter")).toBe(true);
    expect(has("Lab report")).toBe(true);
    expect(has("Quiz")).toBe(false);
    expect(has("Old essay")).toBe(false);
    expect(has("Vanished event")).toBe(false);
  });

  it("Restore posts, announces, and the entry leaves after the refetch", async () => {
    const { server } = mount();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Restore Newsletter" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Restored.");
    });
    expect(server.calls.filter((c) => c.method === "POST")).toEqual([
      { method: "POST", path: "/v1/items/noise/restore", query: "" },
    ]);
    await waitFor(() => {
      // The toast still names the item; the ledger no longer lists it.
      expect(screen.getAllByTestId("history-entry").map((li) => li.textContent).join(" ")).not.toContain("Newsletter");
    });
    expect(screen.getByText("Lab report")).toBeInTheDocument();
  });

  it("shows the empty state when there is nothing in 30 days", async () => {
    mount([]);
    expect(await screen.findByText("Nothing done or dismissed in the last 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
  });

  it("shows a fixed error with Retry, never the server's text, and Retry loads it", async () => {
    const { server } = mount(DAYS, true);
    expect(await screen.findByText("Could not load history. Try again.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("secret server text");
    server.failHistory = false;
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Lab report")).toBeInTheDocument();
    expect(screen.queryByText("Could not load history. Try again.")).not.toBeInTheDocument();
  });

  it("keeps the loaded days and shows a notice when a refresh fails (decision 0375)", async () => {
    const { server, client } = mount();
    await screen.findByText("Lab report");
    server.failHistory = true;
    await client.refetchQueries({ queryKey: ["history"] });
    expect(await screen.findByText("Couldn't refresh. Showing your last loaded history.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("secret server text");
    expect(screen.getByText("Lab report")).toBeInTheDocument();
    server.failHistory = false;
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(screen.queryByText("Couldn't refresh. Showing your last loaded history.")).not.toBeInTheDocument();
    });
  });

  it.each([
    ["an object instead of a list", { detail: "oops" }],
    ["a null body", null],
    ["a day without its date", [{ done_by_you: [] }]],
    ["a list that is not an array", [{ day: "2026-11-12", dismissed: "none" }]],
    ["an entry missing its title", [{ day: "2026-11-12", gone: [{ item_id: "x", at: "2026-11-12T10:00:00Z", group: "gone", outcome: "gone" }] }]],
  ])("treats %s as the error state with the fixed message and Retry, not a crash", async (_label, body) => {
    const { server } = mount(body as unknown as HistoryDay[]);
    expect(await screen.findByText("Could not load history. Try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "History" })).toBeInTheDocument();
    server.days = DAYS;
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Thursday, Nov 12", { selector: "h2" })).toBeInTheDocument();
  });

  it("after a Restore moves focus to the next entry's Restore button", async () => {
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Restore Newsletter" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Restore Lab report" })).toHaveFocus();
    });
  });

  it("after a Restore with no entry left to restore moves focus to the page heading", async () => {
    mount();
    const user = userEvent.setup();
    // The last restorable entry of the list: Lab report.
    await user.click(await screen.findByRole("button", { name: "Restore Lab report" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "History" })).toHaveFocus();
    });
  });

  it("keeps the search and filter when a Restore refetches", async () => {
    mount();
    const user = userEvent.setup();
    await screen.findByText("Lab report");
    await user.click(screen.getByRole("radio", { name: "Done" }));
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "lab");
    await user.click(screen.getByRole("button", { name: "Restore Lab report" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Restored.");
    });
    expect(screen.getByRole("radio", { name: "Done" })).toBeChecked();
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("lab");
  });
});
