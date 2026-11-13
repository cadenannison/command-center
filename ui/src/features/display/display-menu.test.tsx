import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DisplayProvider } from "../../lib/display";
import { SOURCES } from "../../lib/sources";
import { ThemeProvider } from "../../lib/theme";
import { DEFAULT_DOCUMENT } from "./display-api";
import { DisplayMenu } from "./display-menu";
import { DisplaySettingsProvider } from "./display-settings";

const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function stub(initial: Record<string, unknown> = {}) {
  const puts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      if (input.method === "PUT") {
        const body = JSON.parse(await input.clone().text()) as Record<string, unknown>;
        puts.push(body);
        return reply({ ...body, revision: 2 });
      }
      return reply({ ...DEFAULT_DOCUMENT, ...initial, revision: 1 });
    }),
  );
  return puts;
}

function Page() {
  const [container, setContainer] = useState<HTMLElement | null>(null);
  return (
    <main ref={setContainer} aria-label="page">
      <DisplayMenu container={container} />
    </main>
  );
}

function renderMenu() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <DisplayProvider>
          <DisplaySettingsProvider>
            <Page />
          </DisplaySettingsProvider>
        </DisplayProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const root = () => document.documentElement;

async function open() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Display" }));
  return { user, dialog: await screen.findByRole("dialog", { name: "Display settings" }) };
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  for (const name of root().getAttributeNames()) if (name.startsWith("data-")) root().removeAttribute(name);
});

describe("DisplayMenu", () => {
  it("opens a non-modal dialog inside the main landmark and leaves the page usable", async () => {
    stub();
    renderMenu();
    const { dialog } = await open();
    expect(within(screen.getByRole("main")).getByRole("dialog", { name: "Display settings" })).toBe(dialog);
    expect(screen.getByRole("button", { name: "Display" })).not.toHaveAttribute("aria-hidden");
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("is operable by keyboard and returns focus to the button on Escape", async () => {
    stub();
    renderMenu();
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole("button", { name: "Display" })).toHaveFocus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog", { name: "Display settings" });
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(dialog).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Display" })).toHaveFocus();
  });

  it("names every control from visible text and offers the ranges the card sets", async () => {
    stub();
    renderMenu();
    const { dialog } = await open();
    for (const name of ["System", "Light", "Dark", "Comfortable", "Compact"]) {
      expect(within(dialog).getByRole("radio", { name })).toBeInTheDocument();
    }
    const zoom = within(dialog).getByRole("slider", { name: /^Zoom/ });
    expect([zoom.getAttribute("min"), zoom.getAttribute("max"), zoom.getAttribute("step")]).toEqual(["70", "130", "10"]);
    const text = within(dialog).getByRole("slider", { name: /^Text size/ });
    expect([text.getAttribute("min"), text.getAttribute("max"), text.getAttribute("step")]).toEqual(["90", "150", "5"]);
    const glow = within(dialog).getByRole("slider", { name: /^Glow/ });
    expect([glow.getAttribute("min"), glow.getAttribute("max"), glow.getAttribute("step")]).toEqual(["0", "1.6", "0.1"]);
    expect(within(dialog).getByRole("checkbox", { name: "High contrast" })).not.toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: "Keyboard shortcuts" })).toBeChecked();
  });

  it("applies a change at once, announces it and saves the whole document", async () => {
    const puts = stub({ privacy_mode: true, owed_replies_as_tasks: true });
    renderMenu();
    const { user, dialog } = await open();
    await waitFor(() => {
      expect(within(dialog).getByRole("slider", { name: /^Zoom/ })).toBeInTheDocument();
    });
    await user.click(within(dialog).getByRole("radio", { name: "Dark" }));
    expect(root()).toHaveAttribute("data-theme", "dark");
    expect(screen.getByTestId("display-live-region")).toHaveTextContent("Theme: Dark.");
    await user.click(within(dialog).getByRole("radio", { name: "Compact" }));
    expect(root()).toHaveAttribute("data-density", "compact");
    await user.click(within(dialog).getByRole("checkbox", { name: "High contrast" }));
    expect(root()).toHaveAttribute("data-contrast", "high");
    fireEvent.change(within(dialog).getByRole("slider", { name: /^Text size/ }), { target: { value: "150" } });
    expect(root()).toHaveAttribute("data-text-scale", "150");
    fireEvent.change(within(dialog).getByRole("slider", { name: /^Zoom/ }), { target: { value: "130" } });
    expect(within(dialog).getByText("130%")).toBeInTheDocument();
    await waitFor(() => {
      expect(puts).toHaveLength(1);
    }, { timeout: 3000 });
    expect(puts[0]).toMatchObject({
      theme: "dark",
      density: "compact",
      high_contrast: true,
      text_scale: 150,
      zoom: 130,
      privacy_mode: true,
      owed_replies_as_tasks: true,
    });
    await waitFor(() => {
      expect(within(dialog).getByTestId("display-save-status")).toHaveTextContent("Display settings saved.");
    });
  });

  it("turns the shortcuts setting off and announces it", async () => {
    const puts = stub();
    renderMenu();
    const { user, dialog } = await open();
    await user.click(within(dialog).getByRole("checkbox", { name: "Keyboard shortcuts" }));
    expect(within(dialog).getByRole("checkbox", { name: "Keyboard shortcuts" })).not.toBeChecked();
    expect(screen.getByTestId("display-live-region")).toHaveTextContent("Keyboard shortcuts off.");
    await waitFor(() => {
      expect(puts[0]).toMatchObject({ shortcuts: false });
    }, { timeout: 3000 });
  });

  it("offers each source the six token colors only, with a swatch and the contrast result", async () => {
    stub();
    renderMenu();
    const { user, dialog } = await open();
    for (const source of SOURCES) {
      const select = within(dialog).getByRole("combobox", { name: source.name });
      expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "Violet",
        "Rose",
        "Teal",
        "Amber",
        "Sky",
        "Silver",
      ]);
      expect(select).toHaveAccessibleDescription(/^Contrast \d+\.\d:1, passes AA$/);
    }
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Gmail" }), "rose");
    expect(root()).toHaveAttribute("data-src-gmail", "rose");
    expect(screen.getByTestId("display-live-region")).toHaveTextContent("Gmail color: Rose.");
    expect(within(dialog).getByRole("combobox", { name: "Gmail" })).toHaveValue("rose");
  });

  it("keeps a green or pink choice made elsewhere when another source changes", async () => {
    const puts = stub({ source_colors: { wx: "green" } });
    renderMenu();
    const { user, dialog } = await open();
    await waitFor(() => {
      expect(root()).not.toHaveAttribute("data-src-wx");
    });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Gmail" }), "teal");
    await waitFor(() => {
      expect(puts).toHaveLength(1);
    }, { timeout: 3000 });
    expect(puts[0]?.["source_colors"]).toEqual({ wx: "green", gmail: "teal" });
  });

  it("shows reduced motion as a read-only status line with no control", async () => {
    stub();
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    renderMenu();
    const { dialog } = await open();
    expect(within(dialog).getByTestId("reduced-motion")).toHaveTextContent("Reduced motion follows your system setting. It is currently on, so animation is off.");
    expect(within(dialog).queryByRole("checkbox", { name: /motion/i })).toBeNull();
  });
});
