import { api, unwrap, type ApiClient } from "../../api/client";
import type { components } from "../../api/generated/schema";

export type DisplayDocument = components["schemas"]["DisplayInput"];
export type StoredDisplay = components["schemas"]["DisplaySettings"];
export type SourceColorName = NonNullable<DisplayDocument["source_colors"]>[string];

/** What the server returns when nothing is saved yet (revision 0). Used before the first read and when it fails. */
export const DEFAULT_DOCUMENT: DisplayDocument = {
  theme: "system",
  high_contrast: false,
  density: "comfortable",
  glow: 1,
  text_scale: 100,
  privacy_mode: false,
  owed_replies_as_tasks: false,
  zoom: 100,
  shortcuts: true,
};

/** The document the server accepts: exactly its keys, copied one by one. `revision` and `updated_at` never go
 *  back (the input is strict, decision 0356), and every key the UI has no control for rides along unchanged. */
export function toDocument(source: DisplayDocument): DisplayDocument {
  return {
    theme: source.theme,
    high_contrast: source.high_contrast,
    density: source.density,
    glow: source.glow,
    text_scale: source.text_scale,
    privacy_mode: source.privacy_mode,
    owed_replies_as_tasks: source.owed_replies_as_tasks,
    zoom: source.zoom,
    shortcuts: source.shortcuts,
    ...(source.source_colors ? { source_colors: { ...source.source_colors } } : {}),
  };
}

export interface StoredDocument {
  readonly document: DisplayDocument;
  readonly revision: number;
}

function stored(data: StoredDisplay): StoredDocument {
  return { document: toDocument(data), revision: data.revision };
}

export async function fetchDisplay(client: ApiClient = api): Promise<StoredDocument> {
  return stored(await unwrap(() => client.GET("/v1/display-settings")));
}

/** Replace the settings if the stored revision is `revision` (If-Match). A stale one is an ApiError with status 409. */
export async function replaceDisplay(
  document: DisplayDocument,
  revision: number,
  client: ApiClient = api,
): Promise<StoredDocument> {
  return stored(
    await unwrap(() =>
      client.PUT("/v1/display-settings", {
        params: { header: { "if-match": `"${String(revision)}"` } },
        body: toDocument(document),
      }),
    ),
  );
}
