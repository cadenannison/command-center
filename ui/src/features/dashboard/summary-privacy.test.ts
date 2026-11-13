import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { EMAIL_LINE, NEVER_SENT_LINE, SENT_LINE, TITLE_LIMIT, privacyLines, producedBy } from "./summary-privacy";

// Wording test (decision 0333): each claim in summary-privacy.ts is checked against the Python it describes. These are
// checks of the source text, since the UI cannot run the backend; they fail when the code or the wording drifts.
const SRC = resolve(import.meta.dirname, "../../../../src/command_center");
const read = (rel: string) => readFileSync(resolve(SRC, rel), "utf8");

const coreSummary = read("core/summary.py");
const service = read("services/summary.py");
const schema = read("core/schema.py");
const config = read("config.py");

/** The source of one top-level function, from its def line to the next top-level def. */
function functionSource(source: string, name: string): string {
  const start = source.indexOf(`def ${name}(`);
  expect(start, `def ${name} exists`).toBeGreaterThanOrEqual(0);
  const rest = source.slice(start + 1);
  const next = rest.search(/\n(?:def |class |@)/);
  return next === -1 ? source.slice(start) : source.slice(start, start + 1 + next);
}

describe("claim: a redacted title trimmed to 80 characters", () => {
  it("TITLE_LIMIT is core/summary.py ITEM_TEXT_LIMIT", () => {
    const match = /^ITEM_TEXT_LIMIT = (\d+)$/m.exec(coreSummary);
    expect(Number(match?.[1])).toBe(TITLE_LIMIT);
    expect(TITLE_LIMIT).toBe(80);
  });

  it("build_prompt redacts the title, then trims it to that limit", () => {
    const build = functionSource(coreSummary, "build_prompt");
    expect(build).toContain("trim(redact(_collapse(event.title)), ITEM_TEXT_LIMIT)");
  });
});

describe("claim: only the kind, the title and the due date are sent", () => {
  it("build_prompt reads no event field but kind, title and due", () => {
    const build = functionSource(coreSummary, "build_prompt");
    const fields = new Set([...build.matchAll(/\bevent\.(\w+)/g)].map((m) => m[1]));
    expect([...fields].sort()).toEqual(["due", "kind", "title"]);
  });

  it("the prompt line is the kind, the text and the due date", () => {
    const build = functionSource(coreSummary, "build_prompt");
    expect(build).toContain('line = f"- [{event.kind}] {text}"');
    expect(build).toContain('line += f" (due {event.due.date().isoformat()})"');
  });

  it("the service sends nothing but that prompt to the provider", () => {
    expect(service).toContain("prompt = build_prompt(events, self._include_email, day)");
    expect([...service.matchAll(/\._provider\.summarize\(([^)]*)\)/g)].map((m) => m[1])).toEqual(["prompt"]);
  });
});

describe("claim: notes are never sent", () => {
  it("an Event carries has_note, a flag, and no field that could hold note text or a body", () => {
    const eventClass = schema.slice(schema.indexOf("class Event("), schema.indexOf("class ValidationResult"));
    const fields = [...eventClass.matchAll(/^ {4}(\w+): /gm)].map((m) => m[1]);
    expect(fields).toContain("has_note");
    expect(fields.filter((f) => /note|body|text|content|snippet|description/.test(f ?? ""))).toEqual(["has_note"]);
    expect(eventClass).toMatch(/has_note: bool = False/);
  });

  it("the summary code never touches a note or a body", () => {
    for (const source of [coreSummary, service]) {
      expect(source.replace(/#.*$/gm, "")).not.toMatch(/\.note\b|\bnotes\b|\.body\b|\.raw\b/);
    }
  });
});

describe("claim: email is left out unless include_email is on", () => {
  it("build_prompt skips an email event unless include_email", () => {
    expect(functionSource(coreSummary, "build_prompt")).toContain('if event.kind == "email" and not include_email:');
  });

  it("the service drops email events before the prompt unless include_email", () => {
    expect(service).toContain("if not self._include_email:");
    expect(service).toContain('events = [event for event in events if event.kind != "email"]');
  });

  it("the setting is off by default", () => {
    expect(config).toMatch(/^ {4}summary_include_email: bool = False$/m);
    expect(service).toContain("include_email: bool = False,");
  });
});

describe("the copy", () => {
  it("states exactly those claims", () => {
    expect(SENT_LINE).toBe("Written from each item's kind, a redacted title trimmed to 80 characters, and its due date only.");
    expect(NEVER_SENT_LINE).toBe("Notes and email bodies are never sent.");
    expect(EMAIL_LINE).toBe("Email is left out unless it is turned on in the app's configuration.");
    expect(privacyLines()).toEqual([SENT_LINE, NEVER_SENT_LINE, EMAIL_LINE]);
  });

  it("names the provider but never claims where it runs (an Ollama address can be another machine)", () => {
    expect(producedBy("gemini")).toBe("Written by Gemini.");
    expect(producedBy("ollama")).toBe("Written by Ollama.");
    expect(producedBy("something-else")).toBe("Written by your AI provider.");
    expect(producedBy("__proto__")).toBe("Written by your AI provider.");
    const all = [SENT_LINE, NEVER_SENT_LINE, EMAIL_LINE, producedBy("ollama"), producedBy("gemini")].join(" ");
    expect(all).not.toMatch(/this (Mac|machine|computer)|stays|never leaves|local|private/i);
  });

  it("only the providers the backend names get a display name", () => {
    const control = read("services/summary_control.py");
    expect(control).toMatch(/PROVIDERS\s*=\s*\(\s*"gemini",\s*"ollama"\s*\)/);
  });
});
