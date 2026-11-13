import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DisplayProvider } from "../../lib/display";
import { ThemeProvider } from "../../lib/theme";
import { DEFAULT_DOCUMENT } from "./display-api";
import { DisplaySettingsProvider, useDisplaySettings } from "./display-settings";
import { FAILED_TEXT, MERGED_TEXT, SAVED_TEXT } from "./display-saver";

interface Call {
  readonly method: string;
  readonly ifMatch: string | null;
  readonly body: Record<string, unknown> | null;
}

const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const STORED = {
  ...DEFAULT_DOCUMENT,
  theme: "dark",
  privacy_mode: true,
  owed_replies_as_tasks: true,
  source_colors: { gmail: "green", cal: "silver" },
  revision: 4,
  updated_at: "2026-11-12T10:00:00Z",
};

function stub(handler: (call: Call, n: number) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: Request) => {
      const run = async () => {
        const text = await input.clone().text();
        const call: Call = {
          method: input.method,
          ifMatch: input.headers.get("if-match"),
          body: text ? (JSON.parse(text) as Record<string, unknown>) : null,
        };
        calls.push(call);
        return handler(call, calls.length);
      };
      return run();
    }),
  );
  return calls;
}

function Probe() {
  const { settings, update, message, status, loaded } = useDisplaySettings();
  return (
    <div>
      <span data-testid="zoom">{String(settings.zoom)}</span>
      <span data-testid="privacy">{String(settings.privacy_mode)}</span>
      <span data-testid="loaded">{String(loaded)}</span>
      <span data-testid="message">{message}</span>
      <span data-testid="status">{status.kind}</span>
      <button
        onClick={() => {
          update({ zoom: 80 });
        }}
      >
        zoom
      </button>
      <button
        onClick={() => {
          update({ privacy_mode: !settings.privacy_mode });
        }}
      >
        privacy
      </button>
      <button
        onClick={() => {
          update({ glow: 9, text_scale: 1 });
        }}
      >
        extremes
      </button>
    </div>
  );
}

function renderProbe() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <DisplayProvider>
          <DisplaySettingsProvider>
            <Probe />
          </DisplaySettingsProvider>
        </DisplayProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const root = () => document.documentElement;
const wait = { timeout: 3000 };

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  for (const name of root().getAttributeNames()) if (name.startsWith("data-")) root().removeAttribute(name);
});

describe("useDisplaySettings", () => {
  it("reads the stored document and applies it to the root element", async () => {
    stub(() => reply(STORED));
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("loaded")).toHaveTextContent("true");
    });
    await waitFor(() => {
      expect(root()).toHaveAttribute("data-theme", "dark");
    });
    expect(root()).toHaveAttribute("data-src-cal", "silver");
    expect(screen.getByTestId("privacy")).toHaveTextContent("true");
    expect(root().getAttribute("style")).toBeNull();
  });

  it("writes the whole document with If-Match and keeps privacy_mode, owed_replies_as_tasks and source_colors intact", async () => {
    const calls = stub((call) => (call.method === "PUT" ? reply({ ...STORED, ...call.body, revision: 5 }) : reply(STORED)));
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("loaded")).toHaveTextContent("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "zoom" }));
    expect(screen.getByTestId("zoom")).toHaveTextContent("80");
    await waitFor(() => {
      expect(screen.getByTestId("message")).toHaveTextContent(SAVED_TEXT);
    }, wait);
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.ifMatch).toBe('"4"');
    expect(put?.body).toEqual({
      theme: "dark",
      high_contrast: false,
      density: "comfortable",
      glow: 1,
      text_scale: 100,
      privacy_mode: true,
      owed_replies_as_tasks: true,
      zoom: 80,
      shortcuts: true,
      source_colors: { gmail: "green", cal: "silver" },
    });
    expect(put?.body).not.toHaveProperty("revision");
    expect(put?.body).not.toHaveProperty("updated_at");
  });

  it("sends the next change against the revision the last write returned", async () => {
    let revision = 4;
    const calls = stub((call) => {
      if (call.method !== "PUT") return reply(STORED);
      revision += 1;
      return reply({ ...STORED, ...call.body, revision });
    });
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("loaded")).toHaveTextContent("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "zoom" }));
    await waitFor(() => {
      expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    }, wait);
    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("saved");
    });
    fireEvent.click(screen.getByRole("button", { name: "privacy" }));
    await waitFor(() => {
      expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2);
    }, wait);
    expect(calls.filter((c) => c.method === "PUT").map((c) => c.ifMatch)).toEqual(['"4"', '"5"']);
    expect(calls.filter((c) => c.method === "PUT")[1]?.body).toMatchObject({ zoom: 80, privacy_mode: false });
  });

  it("clamps out of range values before they are shown or sent", async () => {
    stub(() => reply(STORED));
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("loaded")).toHaveTextContent("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "extremes" }));
    expect(root()).toHaveAttribute("data-glow", "1.6");
    expect(root()).toHaveAttribute("data-text-scale", "90");
  });

  it("on a 409 reloads the latest, applies the change on top, says so, and keeps what the other writer changed", async () => {
    const LATEST = { ...STORED, privacy_mode: false, high_contrast: true, revision: 9 };
    let puts = 0;
    const calls = stub((call) => {
      if (call.method === "PUT") {
        puts += 1;
        return puts === 1 ? reply({ detail: "secret server words" }, 409) : reply({ ...LATEST, ...call.body, revision: 10 });
      }
      return reply(calls.length > 2 ? LATEST : STORED);
    });
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("loaded")).toHaveTextContent("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "zoom" }));
    await waitFor(() => {
      expect(screen.getByTestId("message")).toHaveTextContent(MERGED_TEXT);
    }, wait);
    const writes = calls.filter((c) => c.method === "PUT");
    expect(writes.map((c) => c.ifMatch)).toEqual(['"4"', '"9"']);
    expect(writes[1]?.body).toMatchObject({ zoom: 80, privacy_mode: false, high_contrast: true });
    expect(root()).toHaveAttribute("data-contrast", "high");
    expect(screen.getByTestId("zoom")).toHaveTextContent("80");
    expect(document.body).not.toHaveTextContent("secret server words");
  });

  it("shows a fixed message when the write fails and keeps the local value for the session", async () => {
    stub((call) => (call.method === "PUT" ? reply({ detail: "loopback only: 10.0.0.5" }, 403) : reply(STORED)));
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId("loaded")).toHaveTextContent("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "zoom" }));
    await waitFor(() => {
      expect(screen.getByTestId("message")).toHaveTextContent(FAILED_TEXT);
    }, wait);
    expect(screen.getByTestId("zoom")).toHaveTextContent("80");
    expect(document.body).not.toHaveTextContent("10.0.0.5");
  });

  it("keeps working on the defaults when the first read fails", async () => {
    const calls = stub(() => reply({ detail: "nope" }, 404));
    renderProbe();
    await waitFor(() => {
      expect(calls.length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId("loaded")).toHaveTextContent("false");
    fireEvent.click(screen.getByRole("button", { name: "zoom" }));
    expect(screen.getByTestId("zoom")).toHaveTextContent("80");
    await waitFor(() => {
      expect(screen.getByTestId("message")).toHaveTextContent(FAILED_TEXT);
    }, wait);
  });

  it("outside a provider reports it is unavailable and changes nothing", () => {
    function Bare() {
      const value = useDisplaySettings();
      return <span data-testid="avail">{`${String(value.available)} ${String(value.settings.zoom)}`}</span>;
    }
    render(<Bare />);
    expect(screen.getByTestId("avail")).toHaveTextContent("false 100");
  });
});
