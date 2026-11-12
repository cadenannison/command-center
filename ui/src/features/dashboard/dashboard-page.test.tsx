import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./dashboard-page";
import { dashboardOf, installGridEnv, json } from "./test-support";
import type { Dashboard } from "./wire";

interface Call {
  readonly method: string;
  readonly path: string;
  readonly ifMatch: string | null;
  readonly body: unknown;
}

type Handler = (call: Call) => Response | Promise<Response>;

function stubApi(handler: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const text = await input.clone().text();
      const call: Call = {
        method: input.method,
        path: new URL(input.url).pathname,
        ifMatch: input.headers.get("if-match"),
        body: text ? (JSON.parse(text) as unknown) : null,
      };
      calls.push(call);
      return handler(call);
    }),
  );
  return calls;
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <DashboardPage />
    </QueryClientProvider>,
  );
  return client;
}

const widgetX = (id: string) => screen.getByTestId(`widget-${id}`).getAttribute("data-x");

async function moveEventsLeft() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Edit" }));
  const header = screen.getByRole("button", { name: /^Events W\d/ });
  fireEvent.keyDown(header, { key: "Enter" });
  fireEvent.keyDown(header, { key: "ArrowLeft" });
  fireEvent.keyDown(header, { key: "Enter" });
  return user;
}

beforeEach(() => {
  installGridEnv(1200, 1400);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("DashboardPage loading", () => {
  it("shows the dashboard's widgets from the typed client", async () => {
    stubApi(() => json([dashboardOf("main", "Main")]));
    renderPage();
    expect(await screen.findByTestId("widget-events-2")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Main", selected: true })).toBeInTheDocument();
  });

  it("creates Main from the default layout when there are no dashboards", async () => {
    const calls = stubApi((call) => (call.method === "POST" ? json(dashboardOf("main", "Main"), 201) : json([])));
    renderPage();
    expect(await screen.findByTestId("widget-needs_me-1")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ name: "Main", layout: { version: 1 } });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("shows an error with Retry when the list cannot be loaded", async () => {
    let fail = true;
    stubApi(() => (fail ? json({ detail: "boom" }, 500) : json([dashboardOf("main", "Main")])));
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("widget-events-2")).toBeInTheDocument();
  });

  it("shows an error with Retry when Main cannot be created", async () => {
    stubApi((call) => (call.method === "POST" ? json({ detail: "boom" }, 500) : json([])));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not create your first dashboard.");
  });
});

describe("DashboardPage tabs", () => {
  it("switches between dashboards without saving anything", async () => {
    const other = dashboardOf("work", "Work", 1, { version: 1, items: [] });
    const calls = stubApi(() => json([dashboardOf("main", "Main"), other]));
    renderPage();
    await screen.findByTestId("widget-events-2");
    await userEvent.click(screen.getByRole("tab", { name: "Work" }));
    expect(screen.queryByTestId("widget-events-2")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Work", selected: true })).toBeInTheDocument();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("moves between tabs with the arrow keys", async () => {
    stubApi(() => json([dashboardOf("main", "Main"), dashboardOf("work", "Work", 1, { version: 1, items: [] })]));
    renderPage();
    await screen.findByTestId("widget-events-2");
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    expect(await screen.findByRole("tab", { name: "Work", selected: true })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Work" })).toHaveFocus();
    });
  });
});

describe("DashboardPage saving", () => {
  it("saves a keyboard move with If-Match when edit mode is left", async () => {
    const calls = stubApi((call) =>
      call.method === "PUT" ? json({ ...dashboardOf("main", "Main", 2) }) : json([dashboardOf("main", "Main")]),
    );
    renderPage();
    const user = await moveEventsLeft();
    expect(widgetX("events-2")).toBe("6");
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "PUT")).toBe(true);
    });
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe("/v1/dashboards/main");
    expect(put?.ifMatch).toBe('"1"');
    expect(JSON.stringify(put?.body)).toContain('"x":6');
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("refetches on a 409, shows the latest version and tells the user", async () => {
    const latest = dashboardOf("main", "Main", 5, {
      version: 1,
      items: [
        {
          id: "events-9",
          widgetId: "events",
          x: 0,
          y: 0,
          w: 5,
          h: 10,
          pinned: false,
          sources: ["cal"],
          options: {},
        },
      ],
    });
    let gets = 0;
    stubApi((call) => {
      if (call.method === "PUT") return json({ detail: "stale" }, 409);
      gets += 1;
      return json([gets === 1 ? dashboardOf("main", "Main") : latest]);
    });
    renderPage();
    const user = await moveEventsLeft();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByText(/changed somewhere else\. Showing the latest version/)).toBeInTheDocument();
    expect(await screen.findByTestId("widget-events-9")).toBeInTheDocument();
    expect(screen.queryByTestId("widget-events-2")).not.toBeInTheDocument();
    expect(gets).toBe(2);
    expect(screen.getByText(/Showing the latest version/).closest("[role=status]")).toHaveFocus();
  });

  it("uses the new revision for the next save after a 409", async () => {
    const latest: Dashboard = dashboardOf("main", "Main", 5);
    let gets = 0;
    const calls = stubApi((call) => {
      if (call.method === "PUT")
        return calls.filter((c) => c.method === "PUT").length === 1
          ? json({}, 409)
          : json(dashboardOf("main", "Main", 6));
      gets += 1;
      return json([gets === 1 ? dashboardOf("main", "Main") : latest]);
    });
    renderPage();
    const user = await moveEventsLeft();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByText(/Showing the latest version/);
    await moveEventsLeft();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await waitFor(() => {
      expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2);
    });
    expect(calls.filter((c) => c.method === "PUT")[1]?.ifMatch).toBe('"5"');
  });

  it("shows an error with Retry when a save fails, and the retry sends the change", async () => {
    let fail = true;
    const calls = stubApi((call) => {
      if (call.method !== "PUT") return json([dashboardOf("main", "Main")]);
      return fail ? json({ detail: "boom" }, 500) : json(dashboardOf("main", "Main", 2));
    });
    renderPage();
    const user = await moveEventsLeft();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your last change was not saved.");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2);
  });

  it("keeps the dashboard open when a tab switch would lose an unsaved change", async () => {
    stubApi((call) =>
      call.method === "PUT"
        ? json({}, 500)
        : json([dashboardOf("main", "Main"), dashboardOf("work", "Work", 1, { version: 1, items: [] })]),
    );
    renderPage();
    await moveEventsLeft();
    await userEvent.click(screen.getByRole("tab", { name: "Work" }));
    expect(await screen.findByText(/has not been saved yet, so this dashboard stays open/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Main", selected: true })).toBeInTheDocument();
  });

  it("drops the 'not saved' alert once a retry succeeds", async () => {
    let fail = true;
    stubApi((call) => {
      if (call.method !== "PUT") {
        return json([dashboardOf("main", "Main"), dashboardOf("work", "Work", 1, { version: 1, items: [] })]);
      }
      return fail ? json({}, 500) : json(dashboardOf("main", "Main", 2));
    });
    renderPage();
    const user = await moveEventsLeft();
    await user.click(screen.getByRole("tab", { name: "Work" }));
    expect(await screen.findByText(/has not been saved yet/)).toBeInTheDocument();
    fail = false;
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.queryByText(/has not been saved yet/)).not.toBeInTheDocument();
  });
});

describe("DashboardPage edit mode and columns", () => {
  it("offers Edit at 12 columns", async () => {
    stubApi(() => json([dashboardOf("main", "Main")]));
    renderPage();
    expect(await screen.findByRole("button", { name: "Edit" })).toBeEnabled();
  });

  it("is read-only with a notice below 12 columns", async () => {
    installGridEnv(900, 1000);
    stubApi(() => json([dashboardOf("main", "Main")]));
    renderPage();
    await screen.findByTestId("widget-events-2");
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByText(/shows 8 columns, so the dashboard is read-only/)).toBeInTheDocument();
  });

  it("announces edit mode and each move in the live region", async () => {
    stubApi(() => json([dashboardOf("main", "Main")]));
    renderPage();
    await moveEventsLeft();
    expect(screen.getByTestId("live-region")).toHaveTextContent(/^Dropped Events at column 7, row 1/);
  });

  it("changes the zoom from the slider", async () => {
    stubApi(() => json([dashboardOf("main", "Main")]));
    renderPage();
    await screen.findByTestId("widget-events-2");
    fireEvent.change(screen.getByRole("slider", { name: /Zoom/ }), {
      target: { value: "70" },
    });
    expect(screen.getByText("70%")).toBeInTheDocument();
  });
});
