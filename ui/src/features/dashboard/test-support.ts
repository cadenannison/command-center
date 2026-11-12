import { vi } from "vitest";
import { DEFAULT_LAYOUTS, type Layout } from "../../layout";
import { layoutToWire, type Dashboard } from "./wire";

/** jsdom has no layout: give every element a fixed width, stub ResizeObserver and set the window width. */
const observers = new Set<() => void>();

/** Tell every mounted grid the size changed (the stubbed ResizeObserver does it on demand). */
export function fireResize(): void {
  for (const callback of observers) callback();
}

export function installGridEnv(containerPx = 1200, windowPx = 1400): void {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private readonly callback: () => void;
      constructor(callback: () => void) {
        this.callback = callback;
      }
      observe() {
        observers.add(this.callback);
      }
      unobserve() {}
      disconnect() {
        observers.delete(this.callback);
      }
    },
  );
  Object.defineProperty(window, "innerWidth", {
    value: windowPx,
    configurable: true,
    writable: true,
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    width: containerPx,
    height: 0,
    top: 0,
    left: 0,
    right: containerPx,
    bottom: 0,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
}

/** Two widgets side by side: Needs me (x0, 7 wide) and Events (x7, 5 wide), both 10 tall. */
export const MINIMAL: Layout = DEFAULT_LAYOUTS.minimal;

export function dashboardOf(id: string, name: string, revision = 1, layout: Layout = MINIMAL): Dashboard {
  return {
    id,
    name,
    position: 0,
    layout: layoutToWire(layout),
    revision,
    updated_at: "2026-11-12T10:00:00Z",
  };
}

export const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
