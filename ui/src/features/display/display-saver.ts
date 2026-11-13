import { ApiError } from "../../api/errors";
import { toDocument, type DisplayDocument, type StoredDocument } from "./display-api";

export type DisplaySaveStatus =
  | { readonly kind: "idle" }
  | { readonly kind: "pending" }
  | { readonly kind: "saving" }
  | { readonly kind: "saved" }
  /** Another writer saved first: the latest was loaded and the change applied on top of it. */
  | { readonly kind: "merged" }
  /** The write failed (or kept conflicting). The local value stays for the session. */
  | { readonly kind: "error" };

export interface DisplaySaverOptions {
  readonly read: () => Promise<StoredDocument>;
  readonly write: (document: DisplayDocument, revision: number) => Promise<StoredDocument>;
  readonly onStatus: (status: DisplaySaveStatus) => void;
  /** The document the server holds after a read or write, with every change still waiting laid over it. */
  readonly onDocument: (document: DisplayDocument) => void;
  readonly delayMs?: number;
}

export const DISPLAY_SAVE_DELAY_MS = 600;

/** Fixed texts; the server's own words never reach the page. */
export const SAVED_TEXT = "Display settings saved.";
export const MERGED_TEXT = "Display settings were changed somewhere else. Your change was applied on top of the latest.";
export const FAILED_TEXT = "Could not save display settings. They apply to this session only.";

/**
 * Debounced, one-at-a-time saving of the whole display document with a revision (decision 0362, applied to a
 * document that has no undo). It keeps the last document the server sent and the keys changed since, and writes
 * server document + changes, so every key the UI has no control for (privacy_mode, owed_replies_as_tasks, source
 * colors) goes back exactly as it was read. On a 409 it reads the latest, lays the same changes on it and writes
 * once more; a second conflict in a row, or any other failure, is `error` and the changes stay queued for the
 * next try (the local value stays on screen either way).
 */
export class DisplaySaver {
  private base: StoredDocument | null = null;
  private pending: Partial<DisplayDocument> = {};
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inFlight: Promise<void> | null = null;
  private stopped = false;

  constructor(private readonly options: DisplaySaverOptions) {}

  get busy(): boolean {
    return this.inFlight !== null || Object.keys(this.pending).length > 0;
  }

  /** Adopt a document the owner read (the first GET, a refetch). Waiting changes stay laid over it. */
  adopt(stored: StoredDocument): void {
    if (this.base && stored.revision < this.base.revision) return;
    this.base = stored;
    this.options.onDocument(this.merged(stored.document));
  }

  change(patch: Partial<DisplayDocument>): void {
    this.pending = { ...this.pending, ...patch };
    this.stopped = false;
    this.options.onStatus({ kind: "pending" });
    this.clearTimer();
    this.timer = setTimeout(() => void this.flush(), this.options.delayMs ?? DISPLAY_SAVE_DELAY_MS);
  }

  /** Send now. Waits for a write in flight first. */
  async flush(): Promise<void> {
    this.clearTimer();
    if (this.inFlight) await this.inFlight;
    if (this.stopped || Object.keys(this.pending).length === 0) return;
    this.inFlight = this.execute().finally(() => {
      this.inFlight = null;
    });
    await this.inFlight;
  }

  dispose(): void {
    this.clearTimer();
  }

  private merged(base: DisplayDocument): DisplayDocument {
    return toDocument({ ...base, ...this.pending });
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private async execute(): Promise<void> {
    this.options.onStatus({ kind: "saving" });
    let merged = false;
    try {
      this.base ??= await this.options.read();
      for (;;) {
        const sent = this.pending;
        this.pending = {};
        try {
          this.base = await this.options.write(toDocument({ ...this.base.document, ...sent }), this.base.revision);
        } catch (error) {
          this.pending = { ...sent, ...this.pending };
          if (!(error instanceof ApiError && error.status === 409) || merged) throw error;
          merged = true;
          this.base = await this.options.read();
          this.options.onDocument(this.merged(this.base.document));
          continue;
        }
        break;
      }
    } catch {
      this.stopped = true;
      this.options.onStatus({ kind: "error" });
      return;
    }
    this.options.onDocument(this.merged(this.base.document));
    if (Object.keys(this.pending).length > 0) {
      await this.execute();
      return;
    }
    this.options.onStatus({ kind: merged ? "merged" : "saved" });
  }
}
