import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_DOCUMENT, type DisplayDocument, type StoredDocument } from "./display-api";
import { DISPLAY_SAVE_DELAY_MS, DisplaySaver } from "./display-saver";

const stored = (revision: number): StoredDocument => ({ revision, document: { ...DEFAULT_DOCUMENT } });

function setup(write: (document: DisplayDocument, revision: number) => Promise<StoredDocument>) {
  const onStatus = vi.fn();
  const onDocument = vi.fn();
  const writeSpy = vi.fn(write);
  const saver = new DisplaySaver({ read: () => Promise.resolve(stored(0)), write: writeSpy, onStatus, onDocument });
  saver.adopt(stored(0));
  onStatus.mockClear();
  onDocument.mockClear();
  return { saver, onStatus, onDocument, writeSpy };
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("DisplaySaver after detach", () => {
  it("calls no callback when a save fails", async () => {
    const h = setup(() => Promise.reject(new Error("offline")));
    h.saver.change({ zoom: 80 });
    h.onStatus.mockClear();
    h.saver.detach();
    h.saver.dispose();
    await h.saver.flush();
    expect(h.writeSpy).toHaveBeenCalledTimes(1);
    expect(h.onStatus).not.toHaveBeenCalled();
    expect(h.onDocument).not.toHaveBeenCalled();
  });

  it("calls no callback when a save succeeds", async () => {
    const h = setup((document, revision) => Promise.resolve({ document, revision: revision + 1 }));
    h.saver.change({ zoom: 80 });
    h.onStatus.mockClear();
    h.saver.detach();
    await h.saver.flush();
    expect(h.onStatus).not.toHaveBeenCalled();
    expect(h.onDocument).not.toHaveBeenCalled();
  });

  it("still completes a write that was already in flight", async () => {
    let finish: (value: StoredDocument) => void = () => undefined;
    const h = setup(() => new Promise<StoredDocument>((resolve) => (finish = resolve)));
    h.saver.change({ zoom: 80 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.writeSpy).toHaveBeenCalledTimes(1);
    h.onStatus.mockClear();
    h.saver.detach();
    finish(stored(1));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.saver.busy).toBe(false);
    expect(h.onStatus).not.toHaveBeenCalled();
    expect(h.onDocument).not.toHaveBeenCalled();
  });

  it("writes a pending change that was never sent", async () => {
    const h = setup((document, revision) => Promise.resolve({ document, revision: revision + 1 }));
    h.saver.change({ zoom: 80 });
    h.saver.detach();
    h.saver.dispose();
    await h.saver.flush();
    expect(h.writeSpy).toHaveBeenCalledTimes(1);
    expect(h.writeSpy.mock.calls[0]?.[0].zoom).toBe(80);
  });

  it("does not throw from a timer that fires after detach", async () => {
    const h = setup((document, revision) => Promise.resolve({ document, revision: revision + 1 }));
    h.saver.change({ zoom: 70 });
    h.saver.detach();
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS * 2);
    expect(h.writeSpy).toHaveBeenCalledTimes(1);
    expect(h.onStatus).toHaveBeenCalledTimes(1); // only the "pending" from change(), made before detach
  });

  it("reports again after attach", async () => {
    const h = setup((document, revision) => Promise.resolve({ document, revision: revision + 1 }));
    h.saver.detach();
    h.saver.attach();
    h.saver.change({ zoom: 90 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.onStatus).toHaveBeenLastCalledWith({ kind: "saved" });
  });
});
