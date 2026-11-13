import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Tier } from "../../layout";
import { json } from "./test-support";
import type { TaskItem } from "./tasks-model";
import { TasksWidget } from "./tasks-widget";

const HOUR = 3_600_000;
const iso = (offset: number) => new Date(Date.now() + offset).toISOString();

const task = (id: string, due: string | null, extra: Partial<TaskItem> = {}): TaskItem => ({
  id,
  title: `Essay ${id}`,
  source: "canvas",
  due,
  link: null,
  done: false,
  priority: 7,
  reasons: [
    { code: "due_soon", text: "Due within a day", points: 4 },
    { code: "canvas", text: "From Canvas", points: 2 },
  ],
  ...extra,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mount(handler: () => Response | Promise<Response>, tiers: { w: Tier; h: Tier } = { w: 3, h: 3 }) {
  const fetchMock = vi.fn(async () => handler());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TasksWidget title="Tasks" source="canvas" status="Canvas" widthTier={tiers.w} heightTier={tiers.h} />
    </QueryClientProvider>,
  );
  return { fetchMock, client };
}

describe("TasksWidget states", () => {
  it("shows loading, then rows", async () => {
    mount(() => json([task("a", iso(HOUR))]));
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(await screen.findByText("Essay a")).toBeInTheDocument();
  });

  it("shows the empty state when nothing is open", async () => {
    mount(() => json([task("a", iso(HOUR), { done: true })]));
    expect(await screen.findByText("All clear. Nothing due.")).toBeInTheDocument();
    expect(screen.queryByText("Essay a")).not.toBeInTheDocument();
  });

  it("shows an error with Retry, and Retry fetches again", async () => {
    let fail = true;
    const { fetchMock } = mount(() =>
      fail ? json({ detail: "secret server text" }, 500) : json([task("a", iso(HOUR))]),
    );
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/Can't reach tasks/)).toBeInTheDocument();
    expect(within(alert).getByText("Could not load tasks. Try again.")).toBeInTheDocument();
    expect(alert).not.toHaveTextContent("secret server text");
    fail = false;
    await userEvent.setup().click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Essay a")).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("keeps older rows and says so when a refresh fails (stale)", async () => {
    let fail = false;
    const { client } = mount(() => (fail ? json({ detail: "x" }, 500) : json([task("a", iso(HOUR))])), { w: 2, h: 3 });
    await screen.findByText("Essay a");
    fail = true;
    await client.refetchQueries({ queryKey: ["tasks"] });
    expect(await screen.findByText(/Showing older data/)).toBeInTheDocument();
    expect(screen.getByText("Essay a")).toBeInTheDocument();
  });

  it("is read-only: it only issues same-origin GET /v1/tasks", async () => {
    const { fetchMock } = mount(() => json([task("a", iso(HOUR))]));
    await screen.findByText("Essay a");
    const requests = fetchMock.mock.calls as unknown as [Request][];
    expect(requests.length).toBeGreaterThan(0);
    for (const [request] of requests) {
      expect(request.method).toBe("GET");
      expect(new URL(request.url).pathname).toBe("/v1/tasks");
      expect(new URL(request.url).origin).toBe(window.location.origin);
    }
  });
});

describe("TasksWidget rows", () => {
  const items = [
    task("over", iso(-2 * HOUR)),
    task("soon", iso(5 * HOUR)),
    task("far", iso(100 * HOUR)),
    task("none", null),
    task("gone", iso(HOUR), { done: true }),
  ];

  it("groups the open items, labels No due date last and hides done ones", async () => {
    mount(() => json(items));
    await screen.findByText("Essay over");
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Overdue", "Due in the next 48 hours", "Later", "No due date"]);
    expect(screen.queryByText("Essay gone")).not.toBeInTheDocument();
    expect(screen.getByText("4 open")).toBeInTheDocument();
  });

  it("W1 shows the title and pill only", async () => {
    mount(() => json([task("a", iso(HOUR))]), { w: 1, h: 3 });
    const row = await screen.findByTestId("task-row");
    expect(row.querySelector('[data-priority="7"]')).toHaveTextContent("Priority 7");
    expect(row.querySelector("[data-source]")).toBeNull();
    expect(within(row).queryByText(/Today|Tomorrow/)).toBeNull();
    expect(within(row).queryByText("Due within a day")).toBeNull();
  });

  it("W2 adds the due time and the source dot", async () => {
    mount(() => json([task("a", iso(HOUR))]), { w: 2, h: 3 });
    const row = await screen.findByTestId("task-row");
    expect(row.textContent).toMatch(/(AM|PM)/);
    expect(row.querySelector('[data-source="canvas"]')).not.toBeNull();
    expect(within(row).queryByText("Due within a day")).toBeNull();
  });

  it("W3 adds the top reason sentence", async () => {
    mount(() => json([task("a", iso(HOUR))]), { w: 3, h: 3 });
    expect(await screen.findByText("Due within a day")).toBeInTheDocument();
    expect(screen.queryByText("From Canvas")).not.toBeInTheDocument();
  });

  it("H1 shows the top 3 rows and a +N more count", async () => {
    mount(() => json(["a", "b", "c", "d", "e"].map((id) => task(id, iso(HOUR)))), { w: 2, h: 1 });
    await screen.findByText("Essay a");
    expect(screen.getAllByTestId("task-row")).toHaveLength(3);
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("expands every reason with its points in place, by keyboard, and collapses again", async () => {
    mount(() => json([task("a", iso(HOUR))]), { w: 3, h: 3 });
    const user = userEvent.setup();
    const toggle = await screen.findByRole("button", { name: "Essay a" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(panel).toHaveTextContent("Due within a day");
    expect(panel).toHaveTextContent("+4 points");
    expect(panel).toHaveTextContent("From Canvas");
    expect(panel).toHaveTextContent("+2 points");
    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
  });
});

describe("TasksWidget links", () => {
  it("renders an http(s) link that opens in a new tab and names the task", async () => {
    mount(() => json([task("a", iso(HOUR), { link: "https://canvas.example.edu/a" })]));
    const link = await screen.findByRole("link", { name: "Open Essay a in a new tab" });
    expect(link).toHaveAttribute("href", "https://canvas.example.edu/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it.each(["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd"])("renders no link for %s", async (link) => {
    mount(() => json([task("a", iso(HOUR), { link })]));
    await screen.findByText("Essay a");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders no link when there is none", async () => {
    mount(() => json([task("a", iso(HOUR))]));
    await screen.findByText("Essay a");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
