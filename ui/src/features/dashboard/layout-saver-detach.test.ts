import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Layout } from "../../layout";
import { LayoutSaver, SAVE_DELAY_MS } from "./layout-saver";

const layout = { items: [] } as unknown as Layout;

function setup(send: (layout: Layout, revision: number) => Promise<number>) {
  const onStatus = vi.fn();
  const sendSpy = vi.fn(send);
  const saver = new LayoutSaver(1, { send: sendSpy, onStatus });
  return { saver, onStatus, sendSpy };
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("LayoutSaver after detach", () => {
  it("reports nothing when an in-flight write resolves after unmount", async () => {
    let finish: (revision: number) => void = () => undefined;
    const h = setup(() => new Promise<number>((resolve) => (finish = resolve)));
    h.saver.schedule(layout);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    expect(h.sendSpy).toHaveBeenCalledTimes(1);
    h.onStatus.mockClear();
    h.saver.detach();
    h.saver.dispose();
    finish(2);
    await vi.advanceTimersByTimeAsync(0);
    expect(h.saver.busy).toBe(false);
    expect(h.saver.currentRevision).toBe(2);
    expect(h.onStatus).not.toHaveBeenCalled();
  });

  it("reports nothing when an in-flight write fails after unmount", async () => {
    let fail: (error: Error) => void = () => undefined;
    const h = setup(() => new Promise<number>((_, reject) => (fail = reject)));
    h.saver.schedule(layout);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    h.onStatus.mockClear();
    h.saver.detach();
    fail(new Error("offline"));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.onStatus).not.toHaveBeenCalled();
  });

  it("still writes a pending change on dispose, silently", async () => {
    const h = setup((_layout, revision) => Promise.resolve(revision + 1));
    h.saver.schedule(layout);
    h.onStatus.mockClear();
    h.saver.detach();
    h.saver.dispose();
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS * 2);
    expect(h.sendSpy).toHaveBeenCalledTimes(1);
    expect(h.onStatus).not.toHaveBeenCalled();
  });

  it("reports again after a StrictMode detach and attach", async () => {
    const h = setup((_layout, revision) => Promise.resolve(revision + 1));
    h.saver.detach();
    h.saver.dispose();
    h.saver.attach();
    h.saver.schedule(layout);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    expect(h.onStatus).toHaveBeenCalledWith({ kind: "pending" });
    expect(h.onStatus).toHaveBeenLastCalledWith({ kind: "saved" });
  });
});
