import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/errors";
import type { Layout } from "../../layout";
import { LayoutSaver, SAVE_DELAY_MS, type SaveStatus } from "./layout-saver";
import { MINIMAL } from "./test-support";

const other: Layout = { ...MINIMAL, items: MINIMAL.items.slice(0, 1) };

function make(send: (layout: Layout, revision: number) => Promise<number>) {
  const statuses: SaveStatus["kind"][] = [];
  const saver = new LayoutSaver(1, {
    send,
    onStatus: (s) => statuses.push(s.kind),
  });
  return { saver, statuses };
}

describe("LayoutSaver", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits for the debounce before sending", async () => {
    const send = vi.fn().mockResolvedValue(2);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS - 1);
    expect(send).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(send).toHaveBeenCalledWith(MINIMAL, 1);
  });

  it("sends only the latest of several quick changes", async () => {
    const send = vi.fn().mockResolvedValue(2);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    saver.schedule(other);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(other, 1);
  });

  it("sends a change made during a save afterwards, with the new revision", async () => {
    let release: (revision: number) => void = () => {};
    const send = vi
      .fn()
      .mockImplementationOnce(() => new Promise<number>((resolve) => (release = resolve)))
      .mockResolvedValue(3);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    saver.schedule(other);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    expect(send).toHaveBeenCalledTimes(1);
    release(2);
    await vi.advanceTimersByTimeAsync(0);
    expect(send).toHaveBeenLastCalledWith(other, 2);
    expect(saver.currentRevision).toBe(3);
  });

  it("reports saving then saved", async () => {
    const { saver, statuses } = make(vi.fn().mockResolvedValue(2));
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    expect(statuses).toEqual(["pending", "saving", "saved"]);
  });

  it("flush sends at once", async () => {
    const send = vi.fn().mockResolvedValue(2);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    await saver.flush();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("stops and reports a conflict on a 409, without retrying", async () => {
    const send = vi.fn().mockRejectedValue(new ApiError("unknown", 409));
    const { saver, statuses } = make(send);
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS * 5);
    expect(statuses.at(-1)).toBe("conflict");
    expect(send).toHaveBeenCalledTimes(1);
    expect(saver.failed).toBe(true);
  });

  it("reports any other failure and keeps the change for a retry", async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError("server", 500)).mockResolvedValue(2);
    const { saver, statuses } = make(send);
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    expect(statuses.at(-1)).toBe("error");
    await saver.retry();
    expect(send).toHaveBeenCalledTimes(2);
    expect(send).toHaveBeenLastCalledWith(MINIMAL, 1);
    expect(statuses.at(-1)).toBe("saved");
  });

  it("rebase adopts the server revision and drops the unsaved change", async () => {
    const send = vi.fn().mockResolvedValue(6);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    saver.rebase(5);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS * 2);
    expect(send).not.toHaveBeenCalled();
    expect(saver.currentRevision).toBe(5);
  });

  it("sends a waiting change at once when disposed, and only once", async () => {
    const send = vi.fn().mockResolvedValue(2);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    saver.dispose();
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS * 2);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("flush waits for a save in flight and then sends the queued change", async () => {
    let release: (revision: number) => void = () => {};
    const send = vi
      .fn()
      .mockImplementationOnce(() => new Promise<number>((resolve) => (release = resolve)))
      .mockResolvedValue(3);
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    saver.schedule(other);
    const flushed = saver.flush();
    release(2);
    await flushed;
    expect(send).toHaveBeenCalledTimes(2);
    expect(send).toHaveBeenLastCalledWith(other, 2);
    expect(saver.busy).toBe(false);
  });

  it("flush reports a failure of the save in flight", async () => {
    let fail: (error: Error) => void = () => {};
    const send = vi.fn().mockImplementation(() => new Promise<number>((_, reject) => (fail = reject)));
    const { saver } = make(send);
    saver.schedule(MINIMAL);
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS);
    const flushed = saver.flush();
    fail(new ApiError("server", 500));
    await flushed;
    expect(saver.failed).toBe(true);
  });
});
