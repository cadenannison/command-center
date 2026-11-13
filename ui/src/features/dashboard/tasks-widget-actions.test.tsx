import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/toast";
import { fakeItemServer } from "../items/actions-test-support";
import type { TaskItem } from "./tasks-model";
import { TasksWidget } from "./tasks-widget";

const task = (id: string): TaskItem => ({
  id,
  title: `Essay ${id}`,
  source: "canvas",
  due: new Date(Date.now() + 3_600_000).toISOString(),
  link: null,
  done: false,
  priority: 7,
  reasons: [{ code: "due_soon", text: "Due within a day", points: 4 }],
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mount(rows: TaskItem[]) {
  const server = fakeItemServer("/v1/tasks", rows);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <main>
        <ToastProvider>
          <TasksWidget title="Tasks" source="canvas" status="Canvas" widthTier={3} heightTier={3} />
        </ToastProvider>
      </main>
    </QueryClientProvider>,
  );
  return server;
}

async function expand(user: ReturnType<typeof userEvent.setup>, title: string) {
  await user.click(await screen.findByRole("button", { name: title }));
}

describe("Tasks row actions", () => {
  it("shows Done, Dismiss and Snooze only in the expanded row", async () => {
    mount([task("a")]);
    const user = userEvent.setup();
    await screen.findByText("Essay a");
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
    await expand(user, "Essay a");
    const group = screen.getByRole("group", { name: "Actions" });
    for (const name of ["Done", "Dismiss", "Snooze"]) expect(within(group).getByRole("button", { name })).toBeEnabled();
  });

  it("Dismiss posts, the row leaves, the toast says so, and Undo restores it", async () => {
    const server = mount([task("a"), task("b")]);
    const user = userEvent.setup();
    await expand(user, "Essay a");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Essay a" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("Essay b")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Dismissed. Essay a");
    expect(server.actionCalls()).toEqual([{ method: "POST", path: "/v1/items/a/dismiss", body: null }]);

    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("button", { name: "Essay a" })).toBeInTheDocument();
    expect(server.actionCalls().at(-1)).toEqual({ method: "POST", path: "/v1/items/a/restore", body: null });
  });

  it("Done posts to the done endpoint and offers Undo", async () => {
    const server = mount([task("a")]);
    const user = userEvent.setup();
    await expand(user, "Essay a");
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Marked done.");
    });
    expect(server.actionCalls()).toEqual([{ method: "POST", path: "/v1/items/a/done", body: null }]);
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("Snooze opens a non-modal menu inside <main> with three presets, and a choice posts the preset", async () => {
    const server = mount([task("a")]);
    const user = userEvent.setup();
    await expand(user, "Essay a");
    const trigger = screen.getByRole("button", { name: "Snooze" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    await user.click(trigger);
    const menu = await screen.findByRole("menu");
    expect(menu.closest("main")).not.toBeNull();
    expect(within(menu).getAllByRole("menuitem").map((el) => el.textContent)).toEqual([
      "Later today",
      "Tomorrow morning",
      "Next week",
    ]);
    // Non-modal: the rest of the page is not hidden from assistive tech.
    expect(screen.getByRole("heading", { name: "Tasks" })).toBeVisible();
    await user.click(within(menu).getByRole("menuitem", { name: "Next week" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Snoozed until next week.");
    });
    expect(server.actionCalls()).toEqual([{ method: "POST", path: "/v1/items/a/snooze", body: { preset: "next_week" } }]);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(server.actionCalls().at(-1)?.path).toBe("/v1/items/a/restore");
    });
  });

  it("the preset menu works by keyboard", async () => {
    const server = mount([task("a")]);
    const user = userEvent.setup();
    await expand(user, "Essay a");
    screen.getByRole("button", { name: "Snooze" }).focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("menu");
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(server.actionCalls()).toHaveLength(1);
    });
    expect(server.actionCalls()[0]?.body).toEqual({ preset: "later_today" });
  });

  it("a failed action shows a fixed message, keeps the row and does not show the server's text", async () => {
    const server = mount([task("a")]);
    server.state.failActions = true;
    const user = userEvent.setup();
    await expand(user, "Essay a");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Could not dismiss it. Try again.");
    });
    expect(document.body).not.toHaveTextContent("secret server text");
    expect(screen.getByText("Essay a")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("disables Done, Dismiss and Snooze on every row while one action is in flight, then enables them", async () => {
    const server = mount([task("a"), task("b")]);
    let release: () => void = () => {};
    server.state.gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const user = userEvent.setup();
    await expand(user, "Essay a");
    await expand(user, "Essay b");
    const groups = screen.getAllByRole("group", { name: "Actions" });
    expect(groups).toHaveLength(2);
    const [rowA, rowB] = groups;
    if (!rowA || !rowB) throw new Error("two rows expected");
    await user.click(within(rowA).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      for (const name of ["Done", "Dismiss", "Snooze"]) {
        expect(within(rowA).getByRole("button", { name })).toBeDisabled();
        expect(within(rowB).getByRole("button", { name })).toBeDisabled();
      }
    });
    expect(server.actionCalls()).toHaveLength(1);
    release();
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Dismissed. Essay a");
    });
    const rowBNow = screen.getByRole("group", { name: "Actions" });
    for (const name of ["Done", "Dismiss", "Snooze"]) {
      await waitFor(() => {
        expect(within(rowBNow).getByRole("button", { name })).toBeEnabled();
      });
    }
    // The toast belongs to the one action that completed.
    expect(server.actionCalls()).toEqual([{ method: "POST", path: "/v1/items/a/dismiss", body: null }]);
  });

  it("marks the toast's item title data-sensitive", async () => {
    mount([task("a")]);
    const user = userEvent.setup();
    await expand(user, "Essay a");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    const toast = await screen.findByTestId("toast");
    expect(toast.querySelector("[data-sensitive]")).toHaveTextContent("Essay a");
  });
});
