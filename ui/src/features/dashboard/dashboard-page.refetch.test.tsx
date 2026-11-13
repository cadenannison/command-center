import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./dashboard-page";
import { dashboardsKey } from "./use-dashboards";
import { dashboardOf, installGridEnv, json } from "./test-support";

/** R10 / Q07 (decision 0375): a failed or competing background refetch must never cost the user their view or edits. */

interface Call {
  readonly method: string;
  readonly ifMatch: string | null;
}
type Handler = (call: Call) => Response | Promise<Response>;

function stubApi(handler: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: Request) => {
      const call: Call = { method: input.method, ifMatch: input.headers.get("if-match") };
      calls.push(call);
      return Promise.resolve(handler(call));
    }),
  );
  return {
    calls,
    puts: () => calls.filter((c) => c.method === "PUT"),
    gets: () => calls.filter((c) => c.method === "GET"),
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <DashboardPage />
    </QueryClientProvider>,
  );
  return { client, ...view };
}

const refetch = (client: QueryClient) =>
  act(async () => {
    await client.refetchQueries({ queryKey: dashboardsKey });
  });

const widgetX = (id: string) => screen.getByTestId(`widget-${id}`).getAttribute("data-x");
const NOTICE = "Couldn't refresh. Showing your last saved view.";

async function moveEventsLeft() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Edit" }));
  const header = screen.getByRole("button", { name: /^Move Events, W\d/ });
  fireEvent.keyDown(header, { key: "Enter" });
  fireEvent.keyDown(header, { key: "ArrowLeft" });
  fireEvent.keyDown(header, { key: "Enter" });
  return user;
}

const work = () => dashboardOf("work", "Work", 1, { version: 1, items: [] });

beforeEach(() => {
  installGridEnv(1200, 1400);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a failed background refetch", () => {
  it("keeps the grid and shows a non-blocking notice with fixed text", async () => {
    let fail = false;
    stubApi((c) => (c.method === "GET" && fail ? json({ detail: "secret-boom" }, 500) : json([dashboardOf("main", "Main")])));
    const { client } = renderPage();
    await screen.findByTestId("widget-events-2");
    fail = true;
    await refetch(client);
    expect(await screen.findByRole("alert")).toHaveTextContent(NOTICE);
    expect(screen.getByTestId("widget-events-2")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Main", selected: true })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("secret-boom");
    expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
  });

  it("keeps unsaved local edits and does not send them early", async () => {
    let fail = false;
    const api = stubApi((c) => (c.method === "GET" && fail ? json({}, 500) : json([dashboardOf("main", "Main")])));
    const { client } = renderPage();
    await moveEventsLeft();
    expect(widgetX("events-2")).toBe("6");
    fail = true;
    await refetch(client);
    expect(await screen.findByRole("alert")).toHaveTextContent(NOTICE);
    expect(widgetX("events-2")).toBe("6");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(api.puts()).toHaveLength(0);
  });

  it("Retry refetches, and the notice clears when it succeeds", async () => {
    let fail = false;
    const api = stubApi((c) => (c.method === "GET" && fail ? json({}, 500) : json([dashboardOf("main", "Main")])));
    const { client } = renderPage();
    await screen.findByTestId("widget-events-2");
    fail = true;
    await refetch(client);
    await screen.findByRole("alert");
    const before = api.gets().length;
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    });
    expect(api.gets().length).toBe(before + 1);
    expect(screen.getByTestId("widget-events-2")).toBeInTheDocument();
  });

  it("Retry that fails again keeps the notice and the edits", async () => {
    let fail = false;
    stubApi((c) => (c.method === "GET" && fail ? json({}, 500) : json([dashboardOf("main", "Main")])));
    const { client } = renderPage();
    const user = await moveEventsLeft();
    fail = true;
    await refetch(client);
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(NOTICE);
    expect(widgetX("events-2")).toBe("6");
  });

  it("still shows the full error panel when there is nothing to show", async () => {
    stubApi(() => json({ detail: "boom" }, 500));
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("a successful refetch while the user has unsaved edits", () => {
  it("does not overwrite them, and the next save still sends the revision it was based on", async () => {
    let revision = 1;
    const api = stubApi((c) => {
      if (c.method === "PUT") return json({}, 409);
      return json([dashboardOf("main", "Main", revision)]);
    });
    const { client } = renderPage();
    const user = await moveEventsLeft();
    revision = 2; // another window saved an unrelated change; the server layout is the original one
    await refetch(client);
    expect(widgetX("events-2")).toBe("6");
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    // The divergence is settled by If-Match: the save carries revision 1 and the server answers 409.
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() => {
      expect(api.puts()).toHaveLength(1);
    });
    expect(api.puts()[0]?.ifMatch).toBe('"1"');
    expect(await screen.findByText(/changed somewhere else/)).toBeInTheDocument();
  });
});

describe("leaving the dashboard with an edit in flight", () => {
  it("a tab switch during a save waits for it, then switches, with one PUT", async () => {
    let release: (r: Response) => void = () => {};
    const api = stubApi((c) =>
      c.method === "PUT"
        ? new Promise<Response>((resolve) => {
            release = resolve;
          })
        : json([dashboardOf("main", "Main"), work()]),
    );
    renderPage();
    const user = await moveEventsLeft();
    await user.click(screen.getByRole("tab", { name: "Work" }));
    await waitFor(() => {
      expect(api.puts()).toHaveLength(1);
    });
    expect(screen.getByRole("tab", { name: "Main", selected: true })).toBeInTheDocument();
    await act(async () => {
      release(json(dashboardOf("main", "Main", 2)));
      await Promise.resolve();
    });
    expect(await screen.findByRole("tab", { name: "Work", selected: true })).toBeInTheDocument();
    expect(api.puts()).toHaveLength(1);
    expect(api.puts()[0]?.ifMatch).toBe('"1"');
  });

  it("a tab switch whose save fails stays on the dashboard and keeps the edit", async () => {
    const api = stubApi((c) => (c.method === "PUT" ? json({}, 500) : json([dashboardOf("main", "Main"), work()])));
    renderPage();
    const user = await moveEventsLeft();
    await user.click(screen.getByRole("tab", { name: "Work" }));
    expect(await screen.findByText(/has not been saved yet/)).toBeInTheDocument();
    expect(widgetX("events-2")).toBe("6");
    expect(api.puts()).toHaveLength(1);
  });

  it("unmounting the page with a pending edit sends exactly one PUT", async () => {
    const api = stubApi((c) => (c.method === "PUT" ? json(dashboardOf("main", "Main", 2)) : json([dashboardOf("main", "Main")])));
    const { unmount } = renderPage();
    await moveEventsLeft();
    expect(api.puts()).toHaveLength(0);
    unmount();
    await waitFor(() => {
      expect(api.puts()).toHaveLength(1);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.puts()).toHaveLength(1);
    expect(api.puts()[0]?.ifMatch).toBe('"1"');
  });
});
