import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SummaryCard } from "./summary-card";
import { CLIP } from "./summary-model";
import { EMAIL_LINE, NEVER_SENT_LINE, SENT_LINE } from "./summary-privacy";
import { json } from "./test-support";
import { SUMMARY_STALE_MS } from "./use-summary";

// Thursday, Nov 12, 2026, 3:30 PM Denver. Only Date is faked, so timers and promises still run.
const NOW = new Date(2026, 10, 12, 15, 30).getTime();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const reply = (summary: Record<string, unknown>, provider = "gemini", extra: Record<string, unknown> = {}) =>
  json({ summary: { headline: "Two deadlines today", priorities: [], heads_up: [], ...summary }, provider, cached: false, ...extra });

function mount(handler: () => Response | Promise<Response>, cols: 4 | 8 | 12 = 12) {
  const fetchMock = vi.fn(async () => handler());
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <SummaryCard cols={cols} />
    </QueryClientProvider>,
  );
  return { fetchMock, client, ...view };
}

const six = ["p1", "p2", "p3", "p4", "p5", "p6"];

describe("SummaryCard states", () => {
  it("shows loading, then the headline", async () => {
    mount(() => reply({}));
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(await screen.findByText("Two deadlines today")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Summary" })).toHaveAttribute("data-state", "ready");
  });

  it("asks GET /v1/summary once for the local day, same origin, read only", async () => {
    const { fetchMock } = mount(() => reply({}));
    await screen.findByText("Two deadlines today");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [[request]] = fetchMock.mock.calls as unknown as [[Request]];
    const url = new URL(request.url);
    expect(request.method).toBe("GET");
    expect(url.origin).toBe(window.location.origin);
    expect(url.pathname).toBe("/v1/summary");
    expect(url.searchParams.get("date")).toBe("2026-11-12");
    expect([...url.searchParams.keys()]).toEqual(["date"]);
  });

  it("shows 'Summaries are off' with a Settings line on the 404, and no Retry or alert", async () => {
    mount(() => json({ detail: "Summaries are off" }, 404));
    expect(await screen.findByText("Summaries are off")).toBeInTheDocument();
    expect(screen.getByText("They can be turned on in Settings.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Summary" })).toHaveAttribute("data-state", "off");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it.each([500, 503, 422, 403])("shows fixed error text and Retry for a %s, never the server's text", async (status) => {
    mount(() => json({ detail: "SECRET-detail-from-server" }, status));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the summary. Try again.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
    expect(screen.queryByText("Summaries are off")).not.toBeInTheDocument();
  });

  it("shows the error for a dropped connection", async () => {
    mount(() => {
      throw new TypeError("Failed to fetch");
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the summary. Try again.");
  });

  it("shows the error when the body is not a summary", async () => {
    mount(() => json([{ id: "x" }]));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("Retry asks again, and a good answer replaces the error", async () => {
    let fail = true;
    const { fetchMock } = mount(() => (fail ? json({}, 500) : reply({})));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fail = false;
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Two deadlines today")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names a stored summary and a template summary, without a date", async () => {
    mount(() => reply({}, "stored"));
    expect(await screen.findByTestId("summary-notice")).toHaveTextContent(/^Showing an earlier summary$/);
    cleanup();
    mount(() => reply({}, "template"));
    expect(await screen.findByTestId("summary-notice")).toHaveTextContent(/^Showing a basic summary$/);
    expect(screen.queryByTestId("summary-caption")).not.toBeInTheDocument();
  });

  it("keeps the summary and says so when a refresh fails", async () => {
    let fail = false;
    const { client } = mount(() => (fail ? json({ detail: "SECRET" }, 500) : reply({})));
    await screen.findByText("Two deadlines today");
    fail = true;
    await act(async () => {
      await client.refetchQueries({ queryKey: ["summary"] });
    });
    expect(await screen.findByText("Couldn't refresh the summary. Showing the last one.")).toBeInTheDocument();
    expect(screen.getByText("Two deadlines today")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  });
});

describe("SummaryCard tiers", () => {
  const full = { priorities: six, heads_up: ["h1", "h2"] };

  it("4 columns: headline and 3 priorities, +N more, no heads-up", async () => {
    mount(() => reply(full), 4);
    await screen.findByText("p1");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["p1", "p2", "p3"]);
    expect(screen.getByTestId("summary-more")).toHaveTextContent("+3 more");
    expect(screen.queryByText("Heads up")).not.toBeInTheDocument();
    expect(screen.queryByText("h1")).not.toBeInTheDocument();
  });

  it("8 columns: 4 priorities and the heads-up below", async () => {
    mount(() => reply(full), 8);
    await screen.findByText("p1");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["p1", "p2", "p3", "p4", "h1", "h2"]);
    expect(screen.getByTestId("summary-more")).toHaveTextContent("+2 more");
    expect(screen.getByTestId("summary-details").className).toContain("grid-cols-1");
  });

  it("12 columns: 5 priorities and the heads-up side by side", async () => {
    mount(() => reply(full), 12);
    await screen.findByText("p1");
    expect(screen.getByTestId("summary-more")).toHaveTextContent("+1 more");
    expect(screen.getAllByRole("listitem")).toHaveLength(7);
    expect(screen.getByTestId("summary-details").className).toContain("grid-cols-2");
  });

  it("shows no +N more when nothing is cut", async () => {
    mount(() => reply({ priorities: ["a", "b"] }), 4);
    await screen.findByText("a");
    expect(screen.queryByTestId("summary-more")).not.toBeInTheDocument();
  });
});

describe("SummaryCard collapse", () => {
  it("collapses to the headline only and expands again, with aria-expanded", async () => {
    mount(() => reply({ priorities: ["p1"], heads_up: ["h1"] }));
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Collapse summary" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("p1")).toBeInTheDocument();
    await user.click(button);
    expect(screen.getByRole("button", { name: "Expand summary" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Two deadlines today")).toBeInTheDocument();
    expect(screen.queryByText("p1")).not.toBeInTheDocument();
    expect(screen.queryByText("h1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("summary-caption")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand summary" }));
    expect(screen.getByText("p1")).toBeInTheDocument();
  });

  it("is expanded by default and is a section labelled by its heading", async () => {
    mount(() => reply({ priorities: ["p1"] }));
    await screen.findByText("p1");
    const region = screen.getByRole("region", { name: "Summary" });
    expect(within(region).getByRole("heading", { level: 2, name: "Summary" })).toBeInTheDocument();
  });

  it("the collapse button name starts with its visible text (WCAG 2.5.3)", async () => {
    mount(() => reply({}));
    const button = await screen.findByRole("button", { name: /^Collapse/ });
    expect(button.textContent).toBe("Collapse summary");
  });
});

describe("SummaryCard untrusted text", () => {
  it("renders HTML-looking strings as literal text, with no elements made from them", async () => {
    const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>';
    const { container } = mount(() =>
      reply({ headline: evil, priorities: ["<b>bold</b> [link](https://evil.example)", "https://evil.example/x"], heads_up: ["<a href='https://evil.example'>go</a>"] }),
    );
    expect(await screen.findByText(evil)).toBeInTheDocument();
    expect(screen.getByText("<b>bold</b> [link](https://evil.example)")).toBeInTheDocument();
    expect(screen.getByText("<a href='https://evil.example'>go</a>")).toBeInTheDocument();
    expect(container.querySelector("img, script, b, a")).toBeNull();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect((window as unknown as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });

  it("never turns a URL into a link", async () => {
    mount(() => reply({ priorities: ["see https://evil.example/path now"] }));
    expect(await screen.findByText("see https://evil.example/path now")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("clips very long strings", async () => {
    const long = "w".repeat(5000);
    mount(() => reply({ headline: long, priorities: [long], heads_up: [long] }));
    const headline = await screen.findByTestId("summary-headline");
    expect(Array.from(headline.textContent).length).toBe(CLIP);
    for (const li of screen.getAllByRole("listitem")) expect(Array.from(li.textContent).length).toBe(CLIP);
  });

  it("ignores an unexpected extra field in the response", async () => {
    mount(() => reply({ extra_html: "<b>x</b>", priorities: ["p1"] }, "gemini", { token: "TOKEN-123", debug: { a: 1 } }));
    await screen.findByText("p1");
    expect(document.body.textContent).not.toContain("TOKEN-123");
    expect(document.body.textContent).not.toContain("extra_html");
    expect(document.body.textContent).not.toContain("<b>x</b>");
  });
});

describe("SummaryCard copy", () => {
  it("names the provider and states what is sent, only for a summary a provider wrote", async () => {
    mount(() => reply({}, "gemini"));
    const caption = await screen.findByTestId("summary-caption");
    expect(caption).toHaveTextContent("Written by Gemini.");
    expect(caption).toHaveTextContent(SENT_LINE);
    expect(caption).toHaveTextContent(NEVER_SENT_LINE);
    expect(caption).toHaveTextContent(EMAIL_LINE);
    expect(caption.textContent).not.toMatch(/on this (Mac|machine|computer)|stays|local/i);
  });

  it("names Ollama without saying where it runs, and falls back for an unknown provider name", async () => {
    mount(() => reply({}, "ollama"));
    expect(await screen.findByTestId("summary-caption")).toHaveTextContent("Written by Ollama.");
    cleanup();
    mount(() => reply({}, "<b>weird</b>"));
    const caption = await screen.findByTestId("summary-caption");
    expect(caption).toHaveTextContent("Written by your AI provider.");
    expect(caption.textContent).not.toContain("weird");
  });
});

describe("SummaryCard fetching", () => {
  it("does not refetch on window focus, reconnect or a minute tick, and a remount inside the stale time reuses the cache", async () => {
    const { fetchMock, client, unmount } = mount(() => reply({}));
    await screen.findByText("Two deadlines today");
    expect(SUMMARY_STALE_MS).toBe(5 * 60_000);
    fireEvent.focus(window);
    window.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("online"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    unmount();
    render(
      <QueryClientProvider client={client}>
        <SummaryCard cols={12} />
      </QueryClientProvider>,
    );
    await screen.findByText("Two deadlines today");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry a failure by itself", async () => {
    const { fetchMock } = mount(() => json({}, 500));
    await screen.findByRole("alert");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
