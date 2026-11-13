/** The privacy claims the Summary card may make, in one place (decision 0333, 0381). Each one is checked against the
 *  Python source it describes by summary-privacy.test.ts; change a line here only together with that test. */

/** core/summary.py ITEM_TEXT_LIMIT: the longest title a provider receives. */
export const TITLE_LIMIT = 80;

export const SENT_LINE = `Written from each item's kind, a redacted title trimmed to ${String(TITLE_LIMIT)} characters, and its due date only.`;
export const NEVER_SENT_LINE = "Notes and email bodies are never sent.";
export const EMAIL_LINE = "Email is left out unless it is turned on in the app's configuration.";

/** Display names for the providers the API can name (SUMMARY providers: gemini, ollama). Anything else gets no name. */
const PROVIDER_LABELS: Readonly<Record<string, string>> = { gemini: "Gemini", ollama: "Ollama" };

/** Who wrote the summary. It names the provider and nothing about where it runs: an Ollama address can be another
 *  machine on the network (decision 0333), so the caption never says "on this Mac". */
export function producedBy(provider: string): string {
  const label = Object.hasOwn(PROVIDER_LABELS, provider) ? PROVIDER_LABELS[provider] : undefined;
  return label ? `Written by ${label}.` : "Written by your AI provider.";
}

/** The lines under a summary a provider wrote. A stored or template summary was not written by a provider this time,
 *  so it gets none of them (the fallback notice says what it is). */
export function privacyLines(): readonly string[] {
  return [SENT_LINE, NEVER_SENT_LINE, EMAIL_LINE];
}
