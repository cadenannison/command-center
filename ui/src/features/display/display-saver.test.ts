import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/errors";
import { DEFAULT_DOCUMENT, type DisplayDocument, type StoredDocument } from "./display-api";
import { DISPLAY_SAVE_DELAY_MS, DisplaySaver, type DisplaySaveStatus } from "./display-saver";

const stored = (revision: number, patch: Partial<DisplayDocument> = {}): StoredDocument => ({
  revision,
  document: { ...DEFAULT_DOCUMENT, ...patch },
});

interface Harness {
  readonly saver: DisplaySaver;
  readonly writes: { document: DisplayDocument; revision: number }[];
  readonly statuses: DisplaySaveStatus["kind"][];
  readonly docs: DisplayDocument[];
  readonly read: ReturnType<typeof vi.fn>;
}

function harness(options: {
  initial?: StoredDocument;
  write?: (document: DisplayDocument, revision: number, call: number) => Promise<StoredDocument>;
  read?: () => Promise<StoredDocument>;
}): Harness {
  const writes: Harness["writes"] = [];
  const statuses: Harness["statuses"] = [];
  const docs: DisplayDocument[] = [];
  const read = vi.fn(options.read ?? (() => Promise.resolve(options.initial ?? stored(0))));
  const saver = new DisplaySaver({
    read,
    write: (document, revision) => {
      writes.push({ document, revision });
      return options.write
        ? options.write(document, revision, writes.length)
        : Promise.resolve({ document, revision: revision + 1 });
    },
    onStatus: (s) => statuses.push(s.kind),
    onDocument: (d) => docs.push(d),
  });
  return { saver, writes, statuses, docs, read };
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("DisplaySaver", () => {
  it("waits for a pause, then writes once with If-Match's revision and every key from the server", async () => {
    const h = harness({});
    h.saver.adopt(stored(3, { privacy_mode: true, owed_replies_as_tasks: true, source_colors: { gmail: "green" } }));
    h.saver.change({ zoom: 80 });
    h.saver.change({ glow: 0.5 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS - 1);
    expect(h.writes).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2);
    expect(h.writes).toHaveLength(1);
    expect(h.writes[0]?.revision).toBe(3);
    expect(h.writes[0]?.document).toEqual({
      ...DEFAULT_DOCUMENT,
      zoom: 80,
      glow: 0.5,
      privacy_mode: true,
      owed_replies_as_tasks: true,
      source_colors: { gmail: "green" },
    });
    expect(h.statuses).toEqual(["pending", "pending", "saving", "saved"]);
  });

  it("sends a change made during a write after it, against the new revision", async () => {
    let release: (value: StoredDocument) => void = () => undefined;
    const h = harness({
      initial: stored(1),
      write: (document, revision, call) =>
        call === 1
          ? new Promise<StoredDocument>((resolve) => {
              release = resolve;
            })
          : Promise.resolve({ document, revision: revision + 1 }),
    });
    h.saver.adopt(stored(1));
    h.saver.change({ zoom: 90 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    h.saver.change({ shortcuts: false });
    release({ document: { ...DEFAULT_DOCUMENT, zoom: 90 }, revision: 2 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS * 2);
    expect(h.writes.map((w) => [w.revision, w.document.zoom, w.document.shortcuts])).toEqual([
      [1, 90, true],
      [2, 90, false],
    ]);
    expect(h.statuses.at(-1)).toBe("saved");
  });

  it("reads the document itself when none was adopted", async () => {
    const h = harness({ initial: stored(7, { privacy_mode: true }) });
    h.saver.change({ zoom: 110 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.read).toHaveBeenCalledTimes(1);
    expect(h.writes[0]).toMatchObject({ revision: 7, document: { zoom: 110, privacy_mode: true } });
  });

  it("on a 409 reads the latest, lays the change on it, writes again and says it merged", async () => {
    const h = harness({
      initial: stored(5, { privacy_mode: true, theme: "dark" }),
      write: (document, revision, call) =>
        call === 1 ? Promise.reject(new ApiError("unknown", 409)) : Promise.resolve({ document, revision: revision + 1 }),
    });
    h.saver.adopt(stored(2));
    h.saver.change({ zoom: 120 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.writes.map((w) => w.revision)).toEqual([2, 5]);
    expect(h.writes[1]?.document).toMatchObject({ zoom: 120, privacy_mode: true, theme: "dark" });
    expect(h.statuses.at(-1)).toBe("merged");
    expect(h.docs.at(-1)).toMatchObject({ zoom: 120, privacy_mode: true, theme: "dark" });
  });

  it("stops with an error on a second conflict in a row and keeps the change for the next try", async () => {
    const h = harness({
      initial: stored(5),
      write: () => Promise.reject(new ApiError("unknown", 409)),
    });
    h.saver.adopt(stored(2));
    h.saver.change({ zoom: 120 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.writes).toHaveLength(2);
    expect(h.statuses.at(-1)).toBe("error");
    expect(h.saver.busy).toBe(true);
    h.saver.change({ glow: 0.2 });
    expect(h.statuses.at(-1)).toBe("pending");
  });

  it("reports any other failure as an error and keeps the local value", async () => {
    const h = harness({ write: () => Promise.reject(new ApiError("forbidden", 403)) });
    h.saver.adopt(stored(1));
    h.saver.change({ zoom: 70 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.writes).toHaveLength(1);
    expect(h.statuses.at(-1)).toBe("error");
  });

  it("reports an error when the first read fails", async () => {
    const h = harness({ read: () => Promise.reject(new ApiError("network")) });
    h.saver.change({ zoom: 70 });
    await vi.advanceTimersByTimeAsync(DISPLAY_SAVE_DELAY_MS);
    expect(h.writes).toHaveLength(0);
    expect(h.statuses.at(-1)).toBe("error");
  });

  it("does not go back to an older revision when adopting", () => {
    const h = harness({});
    h.saver.adopt(stored(4, { zoom: 90 }));
    h.saver.adopt(stored(3, { zoom: 70 }));
    expect(h.docs).toHaveLength(1);
  });

  it("lays waiting changes over a document adopted meanwhile", () => {
    const h = harness({});
    h.saver.change({ zoom: 80 });
    h.saver.adopt(stored(1, { theme: "dark" }));
    expect(h.docs.at(-1)).toMatchObject({ zoom: 80, theme: "dark" });
  });
});
