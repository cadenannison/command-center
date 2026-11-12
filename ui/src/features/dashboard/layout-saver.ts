import { ApiError } from "../../api/errors";
import type { Layout } from "../../layout";

export type SaveStatus =
  | { readonly kind: "idle" }
  | { readonly kind: "pending" }
  | { readonly kind: "saving" }
  | { readonly kind: "saved" }
  | { readonly kind: "conflict" }
  | { readonly kind: "error"; readonly message: string };

export interface SaverOptions {
  /** Send the layout against the revision it was based on; resolves to the new revision. */
  readonly send: (layout: Layout, revision: number) => Promise<number>;
  readonly onStatus: (status: SaveStatus) => void;
  readonly delayMs?: number;
}

export const SAVE_DELAY_MS = 800;

/**
 * Debounced, one-at-a-time saving with revisions. Changes made while a save is in flight are sent after
 * it with the new revision. A 409 stops everything and reports `conflict` (the owner refetches and
 * calls `rebase`); any other failure reports `error` and keeps the layout so `retry` can send it again.
 * Nothing fails silently: every outcome goes through `onStatus`.
 */
export class LayoutSaver {
  private latest: Layout | null = null;
  private inFlight = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private current: Promise<void> | null = null;

  constructor(
    private revision: number,
    private readonly options: SaverOptions,
  ) {}

  get currentRevision(): number {
    return this.revision;
  }

  private get queued(): boolean {
    return this.latest !== null;
  }

  /** True after a failed save, until `retry`, `schedule` or `rebase`. */
  get failed(): boolean {
    return this.stopped;
  }

  /** True while a change is waiting or on its way. */
  get busy(): boolean {
    return this.latest !== null || this.inFlight;
  }

  schedule(layout: Layout): void {
    this.latest = layout;
    this.stopped = false;
    this.options.onStatus({ kind: "pending" });
    this.clearTimer();
    this.timer = setTimeout(() => void this.run(), this.options.delayMs ?? SAVE_DELAY_MS);
  }

  /** Send now (leaving edit mode, switching tabs). Waits for a save in flight, then sends what is queued. */
  async flush(): Promise<void> {
    this.clearTimer();
    if (this.current) await this.current;
    await this.run();
  }

  retry(): Promise<void> {
    this.stopped = false;
    return this.flush();
  }

  /** Adopt the server's revision after a refetch; the unsaved change is dropped. */
  rebase(revision: number): void {
    this.clearTimer();
    this.latest = null;
    this.stopped = false;
    this.revision = revision;
    this.options.onStatus({ kind: "idle" });
  }

  /** The owner is going away: send a waiting change now (best effort; a failure can no longer be shown). */
  dispose(): void {
    this.clearTimer();
    void this.run();
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private run(): Promise<void> {
    if (this.inFlight || this.stopped || this.latest === null) return this.current ?? Promise.resolve();
    this.current = this.execute().finally(() => {
      this.current = null;
    });
    return this.current;
  }

  private async execute(): Promise<void> {
    const layout = this.latest;
    if (layout === null) return;
    this.latest = null;
    this.inFlight = true;
    this.options.onStatus({ kind: "saving" });
    try {
      this.revision = await this.options.send(layout, this.revision);
    } catch (error) {
      this.inFlight = false;
      this.stopped = true;
      this.latest ??= layout;
      const conflict = error instanceof ApiError && error.status === 409;
      this.options.onStatus(
        conflict
          ? { kind: "conflict" }
          : {
              kind: "error",
              message: error instanceof Error ? error.message : "Something went wrong.",
            },
      );
      return;
    }
    this.inFlight = false;
    if (this.queued) {
      await this.run();
      return;
    }
    this.options.onStatus({ kind: "saved" });
  }
}
