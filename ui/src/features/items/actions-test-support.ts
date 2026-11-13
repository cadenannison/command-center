import { vi } from "vitest";
import { json } from "../dashboard/test-support";

export interface ServerCall {
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

/** An in-memory /v1 for the item tests: a list route that returns the rows still visible, and the four item actions.
 *  done, dismiss and snooze hide the row; restore brings it back. `failActions` makes every action a 500. */
export function fakeItemServer(listPath: string, all: readonly { readonly id: string }[]) {
  const hidden = new Set<string>();
  const calls: ServerCall[] = [];
  // `gate`: while set, an action's reply waits for it (to hold one in flight).
  const state: { failActions: boolean; gate: Promise<void> | null } = { failActions: false, gate: null };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const path = new URL(input.url).pathname;
      const text = await input.clone().text();
      calls.push({ method: input.method, path, body: text ? (JSON.parse(text) as unknown) : null });
      if (path === listPath) return json(all.filter((row) => !hidden.has(row.id)));
      const match = /^\/v1\/items\/([^/]+)\/(done|dismiss|snooze|restore)$/.exec(path);
      if (match?.[1] && match[2]) {
        if (state.gate) await state.gate;
        if (state.failActions) return json({ detail: "secret server text" }, 500);
        if (match[2] === "restore") hidden.delete(match[1]);
        else hidden.add(match[1]);
        return json({ id: match[1] });
      }
      return json({ detail: "unexpected" }, 404);
    }),
  );
  const actionCalls = () => calls.filter((c) => c.method === "POST");
  return { calls, actionCalls, state };
}
