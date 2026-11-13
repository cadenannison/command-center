import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Tier } from "../../layout";
import type { NeedsMeItem } from "./needs-me-model";
import { NeedsMeWidget } from "./needs-me-widget";
import { json } from "./test-support";

// Thursday, Nov 12, 2026, 3:30 PM Denver. Only Date is faked, so timers and promises still run.
const NOW = new Date(2026, 10, 12, 15, 30).getTime();
const at = (d: number, h: number, min = 0) => new Date(2026, 10, d, h, min).toISOString();

const row = (id: string, extra: Partial<NeedsMeItem> = {}): NeedsMeItem => ({
  id,
  kind: "task",
  title: `Thing ${id}`,
  source: "canvas",
  at: at(12, 17),
  link: null,
  priority: 7,
  reasons: [
    { code: "due_soon", text: "Due within a day", points: 4 },
    { code: "canvas", text: "From Canvas", points: 2 },
    { code: "old", text: "Not started", points: -1 },
  ],
  ...extra,
});

// The server's order is not the time order on purpose: the widget must not re-sort.
const LIST: NeedsMeItem[] = [
  row("first", { kind: "assignment", title: "Lab report", priority: 9, at: at(12, 9), link: "https://canvas.example.test/a/1" }),
  row("second", { kind: "email", title: "Reply to Dr. Lee", source: "gmail", priority: 8, at: at(13, 10) }),
  row("third", { kind: "event", title: "STAT 121 lecture", source: "apple_calendar", priority: 6, at: at(12, 15) }),
  row("fourth", { kind: "event", title: "Study group", source: "apple_calendar", priority: 5, at: at(12, 17, 30) }),
  row("fifth", { kind: "task", title: "Buy a gift", source: "local", priority: 5, at: at(12, 16) }),
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mount(handler: () => Response | Promise<Response>, tiers: { w: Tier; h: Tier } = { w: 3, h: 3 }) {
  const fetchMock = vi.fn(async () => handler());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NeedsMeWidget title="Needs me" source="cal" status="All sources" widthTier={tiers.w} heightTier={tiers.h} />
    </QueryClientProvider>,
  );
  return { fetchMock, client };
}

const rowsOf = () => screen.findAllByTestId("needs-me-row");

describe("NeedsMeWidget states", () => {
  it("shows loading, then the rows", async () => {
    mount(() => json(LIST));
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(await rowsOf()).toHaveLength(5);
  });

  it("shows a positive empty state when nothing needs you", async () => {
    mount(() => json([]));
    expect(await screen.findByText("Nothing needs you right now")).toBeInTheDocument();
    expect(screen.queryByTestId("needs-me-row")).not.toBeInTheDocument();
  });

  it("shows a fixed error with Retry, never the server's text, and Retry fetches again", async () => {
    let fail = true;
    const { fetchMock } = mount(() => (fail ? json({ detail: "secret server text" }, 500) : json(LIST)));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/Can't reach the Needs me list/)).toBeInTheDocument();
    expect(within(alert).getByText("Could not load what needs you. Try again.")).toBeInTheDocument();
    expect(alert).not.toHaveTextContent("secret server text");
    fail = false;
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await rowsOf()).toHaveLength(5);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeps the older rows and says so when a refresh fails (stale)", async () => {
    let fail = false;
    const { client } = mount(() => (fail ? json({ detail: "x" }, 500) : json(LIST)));
    await rowsOf();
    fail = true;
    await client.refetchQueries({ queryKey: ["needs-me"] });
    expect(await screen.findByText(/Showing older data/)).toBeInTheDocument();
    expect(screen.getAllByTestId("needs-me-row")).toHaveLength(5);
  });

  it("is read-only: it only issues same-origin GET /v1/needs-me", async () => {
    const { fetchMock } = mount(() => json(LIST));
    await rowsOf();
    const requests = fetchMock.mock.calls as unknown as [Request][];
    expect(requests.length).toBeGreaterThan(0);
    for (const [request] of requests) {
      expect(request.method).toBe("GET");
      expect(new URL(request.url).pathname).toBe("/v1/needs-me");
      expect(new URL(request.url).origin).toBe(window.location.origin);
    }
  });
});

describe("NeedsMeWidget rows", () => {
  it("keeps the server's order, whatever the times and priorities", async () => {
    mount(() => json(LIST));
    const rows = await rowsOf();
    expect(rows.map((r) => within(r).getAllByRole("button")[0]?.textContent)).toEqual([
      "Lab report",
      "Reply to Dr. Lee",
      "STAT 121 lecture",
      "Study group",
      "Buy a gift",
    ]);
  });

  it("leaves weather out of the rows and the count", async () => {
    mount(() => json([...LIST.slice(0, 2), row("wx", { kind: "weather", title: "High 58" })]));
    expect(await rowsOf()).toHaveLength(2);
    expect(screen.queryByText("High 58")).not.toBeInTheDocument();
    expect(screen.getByText("2 need you")).toBeInTheDocument();
  });

  it("W2 shows the priority pill, source dot, kind label and time of each row", async () => {
    mount(() => json(LIST), { w: 2, h: 3 });
    const rows = await rowsOf();
    expect(rows.map((r) => within(r).getByTestId("needs-me-kind").textContent)).toEqual(["Assignment", "Reply", "Event", "Event", "Task"]);
    expect(rows.map((r) => within(r).getByTestId("needs-me-when").textContent)).toEqual([
      "Overdue",
      "Due Tomorrow 10:00 AM",
      "Now",
      "Starts 5:30 PM",
      "Due 4:00 PM",
    ]);
    expect(rows.map((r) => r.querySelector("[data-priority]")?.textContent)).toEqual([
      "Priority 9",
      "Priority 8",
      "Priority 6",
      "Priority 5",
      "Priority 5",
    ]);
    expect(rows.map((r) => r.querySelector("[data-source]")?.getAttribute("data-source"))).toEqual(["canvas", "gmail", "cal", "cal", "manual"]);
    expect(within(rows[0] as HTMLElement).queryByText("Due within a day")).toBeNull();
  });

  it("marks an overdue time with text, not only color", async () => {
    mount(() => json(LIST), { w: 2, h: 3 });
    const rows = await rowsOf();
    expect(within(rows[0] as HTMLElement).getByTestId("needs-me-when")).toHaveTextContent("Overdue");
    expect(within(rows[0] as HTMLElement).getByTestId("needs-me-when")).toHaveClass("text-danger");
    expect(within(rows[1] as HTMLElement).getByTestId("needs-me-when")).not.toHaveClass("text-danger");
  });

  it("W3 adds the top reason sentence", async () => {
    mount(() => json(LIST), { w: 3, h: 3 });
    const rows = await rowsOf();
    expect(within(rows[0] as HTMLElement).getByText("Due within a day")).toBeInTheDocument();
  });

  it("W1 shows the count and the top item only", async () => {
    mount(() => json(LIST), { w: 1, h: 3 });
    const rows = await rowsOf();
    expect(rows).toHaveLength(1);
    expect(screen.getByTestId("needs-me-count")).toHaveTextContent("5 need you");
    expect(within(rows[0] as HTMLElement).getByText("Lab report")).toBeInTheDocument();
    expect(rows[0]?.querySelector("[data-source]")).toBeNull();
    expect(screen.queryByTestId("needs-me-more")).not.toBeInTheDocument();
  });

  it("the footer carries the count", async () => {
    mount(() => json(LIST));
    await rowsOf();
    expect(screen.getByText("5 need you")).toBeInTheDocument();
  });
});

describe("NeedsMeWidget height tiers", () => {
  const many = Array.from({ length: 9 }, (_, i) => row(`r${String(i)}`, { title: `Row ${String(i)}` }));

  it.each<[Tier, number, string | null]>([
    [1, 3, "+6 more"],
    [2, 6, "+3 more"],
    [3, 9, null],
  ])("H%i shows %i rows", async (h, shown, more) => {
    mount(() => json(many), { w: 2, h });
    expect(await rowsOf()).toHaveLength(shown);
    if (more === null) expect(screen.queryByTestId("needs-me-more")).not.toBeInTheDocument();
    else expect(screen.getByTestId("needs-me-more")).toHaveTextContent(more);
    expect(screen.getByText("Row 0")).toBeInTheDocument();
  });
});

describe("NeedsMeWidget reasons and links", () => {
  it("opens a disclosure with every reason and its points as text, and closes it again", async () => {
    mount(() => json(LIST), { w: 3, h: 3 });
    const rows = await rowsOf();
    const first = rows[0] as HTMLElement;
    const toggle = within(first).getByRole("button", { name: "Lab report" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const user = userEvent.setup();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle.getAttribute("aria-controls")).toBe(first.querySelector("[id]")?.id);
    expect(first).toHaveTextContent("Due within a day+4 points");
    expect(first).toHaveTextContent("From Canvas+2 points");
    expect(first).toHaveTextContent("Not started−1 points");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(first).not.toHaveTextContent("+4 points");
  });

  it("says so when a row has no reasons", async () => {
    mount(() => json([row("x", { reasons: [] })]), { w: 2, h: 3 });
    await userEvent.setup().click(await screen.findByRole("button", { name: "Thing x" }));
    expect(screen.getByText("No reasons recorded.")).toBeInTheDocument();
  });

  it("links only http and https, in a new tab, with noopener noreferrer and the title in the name", async () => {
    mount(
      () =>
        json([
          row("a", { title: "Safe https", link: "https://canvas.example.test/a" }),
          row("b", { title: "Safe http", link: "http://canvas.example.test/b" }),
          row("c", { title: "Script", link: "javascript:alert(1)" }),
          row("d", { title: "Data", link: "data:text/html,hi" }),
          row("e", { title: "Relative", link: "/v1/secret" }),
          row("f", { title: "None", link: null }),
        ]),
      { w: 2, h: 3 },
    );
    await rowsOf();
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.getAttribute("aria-label"))).toEqual(["Open Safe https in a new tab", "Open Safe http in a new tab"]);
    for (const link of links) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
    expect(links[0]).toHaveAttribute("href", "https://canvas.example.test/a");
  });

  it("prints the priority with visually hidden 'Priority' text for a screen reader", async () => {
    mount(() => json([row("a", { priority: 10 })]), { w: 2, h: 3 });
    const pill = (await rowsOf())[0]?.querySelector("[data-priority]");
    expect(pill).toHaveAttribute("data-priority", "10");
    expect(pill?.querySelector(".sr-only")).toHaveTextContent("Priority");
  });
});
