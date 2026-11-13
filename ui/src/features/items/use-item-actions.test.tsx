import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/toast";
import { json } from "../dashboard/test-support";
import { ITEM_QUERY_KEYS, useItemActions, type SnoozePreset } from "./use-item-actions";

interface Call {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function Buttons() {
  const actions = useItemActions();
  const item = { id: "item-1", title: "Essay" };
  return (
    <>
      <button type="button" onClick={() => { actions.done(item); }}>do done</button>
      <button type="button" onClick={() => { actions.dismiss(item); }}>do dismiss</button>
      <button type="button" onClick={() => { actions.snooze(item, "tomorrow_morning" satisfies SnoozePreset); }}>do snooze</button>
      <button type="button" onClick={() => { actions.restore(item); }}>do restore</button>
      <span data-testid="busy">{String(actions.busy)}</span>
    </>
  );
}

function mount(reply: (call: Call) => Response | Promise<Response> = () => json({ id: "item-1" })) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const text = await input.clone().text();
      const call = { method: input.method, path: new URL(input.url).pathname, body: text ? (JSON.parse(text) as unknown) : null };
      calls.push(call);
      return reply(call);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <Buttons />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { calls, invalidate };
}

describe("useItemActions", () => {
  it.each([
    ["do done", "/v1/items/item-1/done", null, "Marked done."],
    ["do dismiss", "/v1/items/item-1/dismiss", null, "Dismissed."],
    ["do snooze", "/v1/items/item-1/snooze", { preset: "tomorrow_morning" }, "Snoozed until tomorrow morning."],
    ["do restore", "/v1/items/item-1/restore", null, "Restored."],
  ])("%s posts to the right endpoint and announces %s", async (label, path, body, message) => {
    const { calls } = mount();
    await userEvent.setup().click(screen.getByRole("button", { name: label }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(message);
    });
    expect(calls).toEqual([{ method: "POST", path, body }]);
  });

  it("refetches tasks, needs-me, history, events and agenda after a success, but not the summary (decision 0381)", async () => {
    const { invalidate } = mount();
    await userEvent.setup().click(screen.getByRole("button", { name: "do dismiss" }));
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalled();
    });
    const keys = invalidate.mock.calls.map(([filters]) => (filters as { queryKey: string[] }).queryKey[0]);
    for (const key of ["tasks", "needs-me", "history", "events", "agenda"]) expect(keys).toContain(key);
    expect(keys).not.toContain("summary");
    expect(keys).toEqual([...ITEM_QUERY_KEYS]);
  });

  it("Undo calls restore, and for a snooze too", async () => {
    const { calls } = mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "do snooze" }));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(calls.map((c) => c.path)).toEqual(["/v1/items/item-1/snooze", "/v1/items/item-1/restore"]);
    });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Restored.");
    });
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("shows a fixed message on failure, never the server's text, and refetches nothing", async () => {
    const { invalidate } = mount(() => json({ detail: "secret server text" }, 500));
    await userEvent.setup().click(screen.getByRole("button", { name: "do dismiss" }));
    const alert = await screen.findByRole("alert");
    await waitFor(() => {
      expect(alert).toHaveTextContent("Could not dismiss it. Try again.");
    });
    expect(document.body).not.toHaveTextContent("secret server text");
    expect(invalidate).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("a failed network call also shows a fixed message, and Try again repeats the action", async () => {
    let fail = true;
    const { calls } = mount(() => {
      if (fail) throw new TypeError("secret network text");
      return json({ id: "item-1" });
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "do done" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Could not mark it done. Try again.");
    });
    expect(document.body).not.toHaveTextContent("secret network text");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Marked done.");
    });
    expect(calls).toHaveLength(2);
  });

  it("is busy while a request is in flight", async () => {
    let release: (() => void) | undefined;
    mount(
      () =>
        new Promise<Response>((resolve) => {
          release = () => {
            resolve(json({ id: "item-1" }));
          };
        }),
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "do dismiss" }));
    await waitFor(() => {
      expect(screen.getByTestId("busy")).toHaveTextContent("true");
    });
    release?.();
    await waitFor(() => {
      expect(screen.getByTestId("busy")).toHaveTextContent("false");
    });
  });
});
