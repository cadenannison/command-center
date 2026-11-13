import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/toast";
import { fakeItemServer } from "../items/actions-test-support";
import type { NeedsMeItem } from "./needs-me-model";
import { NeedsMeWidget } from "./needs-me-widget";

const item = (id: string): NeedsMeItem => ({
  id,
  kind: "task",
  title: `Thing ${id}`,
  source: "canvas",
  at: new Date(Date.now() + 3_600_000).toISOString(),
  link: null,
  priority: 7,
  reasons: [{ code: "due_soon", text: "Due within a day", points: 4 }],
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mount(rows: NeedsMeItem[]) {
  const server = fakeItemServer("/v1/needs-me", rows);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <main>
        <ToastProvider>
          <NeedsMeWidget title="Needs me" source="cal" status="All sources" widthTier={3} heightTier={3} />
        </ToastProvider>
      </main>
    </QueryClientProvider>,
  );
  return server;
}

async function expand(user: ReturnType<typeof userEvent.setup>, title: string) {
  await user.click(await screen.findByRole("button", { name: title }));
}

describe("Needs me row actions", () => {
  it("shows Done, Dismiss and Snooze only in the expanded row", async () => {
    mount([item("a")]);
    const user = userEvent.setup();
    await screen.findByText("Thing a");
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
    await expand(user, "Thing a");
    const group = screen.getByRole("group", { name: "Actions" });
    for (const name of ["Done", "Dismiss", "Snooze"]) expect(within(group).getByRole("button", { name })).toBeEnabled();
  });

  it("Dismiss posts, the row leaves, and Undo restores it", async () => {
    const server = mount([item("a"), item("b")]);
    const user = userEvent.setup();
    await expand(user, "Thing a");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Thing a" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("Thing b")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Dismissed. Thing a");
    expect(server.actionCalls()).toEqual([{ method: "POST", path: "/v1/items/a/dismiss", body: null }]);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("button", { name: "Thing a" })).toBeInTheDocument();
    expect(server.actionCalls().at(-1)?.path).toBe("/v1/items/a/restore");
  });

  it("Done posts to the done endpoint", async () => {
    const server = mount([item("a")]);
    const user = userEvent.setup();
    await expand(user, "Thing a");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Marked done.");
    });
    expect(server.actionCalls()).toEqual([{ method: "POST", path: "/v1/items/a/done", body: null }]);
  });

  it("Snooze offers three presets in a menu inside <main>, and a choice posts it", async () => {
    const server = mount([item("a")]);
    const user = userEvent.setup();
    await expand(user, "Thing a");
    await user.click(screen.getByRole("button", { name: "Snooze" }));
    const menu = await screen.findByRole("menu");
    expect(menu.closest("main")).not.toBeNull();
    expect(within(menu).getAllByRole("menuitem").map((el) => el.textContent)).toEqual([
      "Later today",
      "Tomorrow morning",
      "Next week",
    ]);
    await user.click(within(menu).getByRole("menuitem", { name: "Tomorrow morning" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Snoozed until tomorrow morning.");
    });
    expect(server.actionCalls()).toEqual([
      { method: "POST", path: "/v1/items/a/snooze", body: { preset: "tomorrow_morning" } },
    ]);
  });

  it("a failed action shows a fixed message and keeps the row", async () => {
    const server = mount([item("a")]);
    server.state.failActions = true;
    const user = userEvent.setup();
    await expand(user, "Thing a");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Could not mark it done. Try again.");
    });
    expect(document.body).not.toHaveTextContent("secret server text");
    expect(screen.getByText("Thing a")).toBeInTheDocument();
  });
});
