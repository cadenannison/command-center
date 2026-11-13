import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_LAYOUTS, WIDGETS, type Layout, type TemplateName } from "../../layout";
import { DashboardView } from "./dashboard-view";
import { downloadText } from "./download";
import { dashboardOf, fireResize, installGridEnv, json } from "./test-support";

vi.mock("./download", () => ({ downloadText: vi.fn() }));

const SUMMARY = { summary: { headline: "A quiet day.", priorities: [], heads_up: [] }, provider: "gemini", cached: true };

beforeEach(() => {
  installGridEnv(1200, 1400);
  vi.stubGlobal(
    "fetch",
    vi.fn((input: Request) => Promise.resolve(new URL(input.url).pathname === "/v1/summary" ? json(SUMMARY) : json([]))),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.mocked(downloadText).mockClear();
});

function mount(layout: Layout = DEFAULT_LAYOUTS.minimal, name = "Main") {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DashboardView dashboard={dashboardOf("main", name, 1, layout)} flushRef={createRef()} onConflict={() => Promise.resolve(true)} />
    </QueryClientProvider>,
  );
}

async function enterEdit() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Edit" }));
  return user;
}

const live = () => screen.getByTestId("live-region");
const expectLive = (text: string) =>
  waitFor(() => {
    expect(live()).toHaveTextContent(text);
  });
const widgetIds = () =>
  screen
    .getAllByTestId(/^widget-/)
    .map((el) => el.getAttribute("data-testid")?.replace("widget-", ""));
const size = (id: string) => {
  const el = screen.getByTestId(`widget-${id}`);
  return `${el.getAttribute("data-w") ?? ""}x${el.getAttribute("data-h") ?? ""}`;
};

async function openMenu(user: ReturnType<typeof userEvent.setup>, title: string) {
  await user.click(screen.getByRole("button", { name: `Options for ${title}` }));
  return screen.findByRole("menu", { name: `Options for ${title}` });
}

describe("edit toolbar states", () => {
  it("is not shown outside edit mode", () => {
    mount();
    expect(screen.queryByRole("group", { name: "Edit tools" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add widget" })).not.toBeInTheDocument();
  });

  it("shows Add widget, Undo, Redo, Reset, Export and Done in edit mode, with Undo and Redo disabled while the history is empty", async () => {
    mount();
    await enterEdit();
    const bar = screen.getByRole("group", { name: "Edit tools" });
    expect(within(bar).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Add widget",
      "Undo",
      "Redo",
      "Reset",
      "Export",
      "Done",
    ]);
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });

  it("is not shown below 12 columns, where the read-only notice applies", async () => {
    mount();
    await enterEdit();
    installGridEnv(900, 1000);
    await act(async () => {
      fireResize();
      await Promise.resolve();
    });
    expect(document.getElementById("dashboard-readonly")).toHaveTextContent("read-only");
    expect(screen.queryByRole("group", { name: "Edit tools" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
  });

  it("Done leaves edit mode and puts focus on the Edit button", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("group", { name: "Edit tools" })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Edit" })).toHaveFocus();
    });
    await expectLive("Edit mode off.");
  });
});

describe("widget gallery", () => {
  it("lists every registry widget with name, kind, description and default size", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a widget" });
    const rows = within(dialog).getAllByRole("listitem");
    expect(rows).toHaveLength(WIDGETS.length);
    const weather = rows.find((r) => r.textContent.includes("Weather"));
    expect(weather).toHaveTextContent("weather");
    expect(weather).toHaveTextContent("High, low and outlook");
    expect(weather).toHaveTextContent("Default size 4×8");
    expect(within(dialog).getByRole("button", { name: "Add Weather" })).toBeEnabled();
  });

  it("adds the chosen widget below the others, announces it, closes and returns focus to Add widget", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    await user.click(await screen.findByRole("button", { name: "Add Weather" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(widgetIds()).toContain("weather-1");
    expect(screen.getByTestId("widget-weather-1")).toHaveAttribute("data-y", "10");
    expect(size("weather-1")).toBe("4x8");
    await expectLive("Added Weather at column 1, row 11, 4 wide, 8 tall.");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Add widget" })).toHaveFocus();
    });
    expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled();
  });

  it("allows a second widget of the same kind with its own id", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    await screen.findByRole("dialog", { name: "Add a widget" });
    await user.click(screen.getByRole("button", { name: "Add Events" }));
    expect(widgetIds()).toEqual(expect.arrayContaining(["events-2", "events-3"]));
  });

  it("traps focus, closes on Escape without adding anything and returns focus to Add widget", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a widget" });
    for (let n = 0; n < 20; n++) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Add widget" })).toHaveFocus();
    });
    expect(widgetIds()).toEqual(["needs_me-1", "events-2"]);
  });
});

describe("undo and redo through the real history", () => {
  it("undoes and redoes an add, enabling and disabling the buttons and announcing each", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Add widget" }));
    await user.click(await screen.findByRole("button", { name: "Add Weather" }));
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(widgetIds()).toEqual(["needs_me-1", "events-2"]);
    await expectLive("Undone.");
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Redo" }));
    expect(widgetIds()).toContain("weather-1");
    await expectLive("Redone.");
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });
});

describe("per-widget menu", () => {
  it("is its own button beside the drag handle, not inside the heading", async () => {
    mount();
    await enterEdit();
    const menu = screen.getByRole("button", { name: "Options for Events" });
    const heading = screen.getByRole("heading", { level: 2, name: "Events" });
    expect(heading.contains(menu)).toBe(false);
    expect(menu.parentElement?.parentElement).toBe(heading.parentElement);
  });

  it("is not there outside edit mode", () => {
    mount();
    expect(screen.queryByRole("button", { name: /^Options for/ })).not.toBeInTheDocument();
  });

  it("opens from the keyboard and offers S, M, L, Pin and Remove", async () => {
    mount();
    const user = await enterEdit();
    screen.getByRole("button", { name: "Options for Events" }).focus();
    await user.keyboard("{Enter}");
    const menu = await screen.findByRole("menu", { name: "Options for Events" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "S · 3×5",
      "M · 4×8",
      "L · 7×10",
      "Pin",
      "Remove",
    ]);
  });

  it("removes the widget, announces it, and moves focus to Add widget because the menu button is gone", async () => {
    mount();
    const user = await enterEdit();
    const menu = await openMenu(user, "Events");
    await user.click(within(menu).getByRole("menuitem", { name: "Remove" }));
    expect(widgetIds()).toEqual(["needs_me-1"]);
    await expectLive("Events removed. Undo brings it back.");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Add widget" })).toHaveFocus();
    });
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(widgetIds()).toEqual(["needs_me-1", "events-2"]);
  });

  it.each([
    ["S", "3x5"],
    ["M", "4x8"],
    ["L", "7x10"],
  ])("size %s resizes Events to %s and announces it", async (name, result) => {
    mount();
    const user = await enterEdit();
    const menu = await openMenu(user, "Events");
    await user.click(within(menu).getByRole("menuitem", { name: new RegExp(`^${name} ·`) }));
    expect(size("events-2")).toBe(result);
    await expectLive(`Events resized to ${result.replace("x", "×")}.`);
    // The menu button keeps the focus the menu gives back.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Options for Events" })).toHaveFocus();
    });
  });

  it("disables a preset the widget's max does not allow, and says why in the item", async () => {
    mount(DEFAULT_LAYOUTS.main);
    const user = await enterEdit();
    const menu = await openMenu(user, "Weather");
    const large = within(menu).getByRole("menuitem", { name: /^L ·/ });
    expect(large).toHaveAttribute("aria-disabled", "true");
    expect(large).toHaveTextContent("Weather is limited to 2×3 up to 6×9.");
    const before = size("weather-6");
    await user.click(large);
    expect(size("weather-6")).toBe(before);
    expect(within(menu).getByRole("menuitem", { name: /^S ·/ })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("disables the size a widget already has", async () => {
    mount();
    const user = await enterEdit();
    // Needs me is 7×10 in Minimal, which is exactly L.
    const menu = await openMenu(user, "Needs me");
    const large = within(menu).getByRole("menuitem", { name: /^L ·/ });
    expect(large).toHaveAttribute("aria-disabled", "true");
    expect(large).toHaveTextContent("Already this size.");
    expect(within(menu).getByRole("menuitem", { name: /^M ·/ })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("pins and unpins, announces, and a pinned widget loses its resize handles and its sizes", async () => {
    mount();
    const user = await enterEdit();
    let menu = await openMenu(user, "Events");
    await user.click(within(menu).getByRole("menuitem", { name: "Pin" }));
    await expectLive("Events pinned. It cannot be moved or resized.");
    expect(within(screen.getByTestId("widget-events-2")).queryByTestId("handle-se")).not.toBeInTheDocument();
    menu = await openMenu(user, "Events");
    for (const name of [/^S ·/, /^M ·/, /^L ·/]) {
      const item = within(menu).getByRole("menuitem", { name });
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(item).toHaveTextContent("Unpin it to resize.");
    }
    await user.click(within(menu).getByRole("menuitem", { name: "Unpin" }));
    await expectLive("Events unpinned.");
    expect(within(screen.getByTestId("widget-events-2")).getByTestId("handle-se")).toBeInTheDocument();
  });

  it("does not start a drag when the menu button is pressed, though the header around it does", async () => {
    mount();
    await enterEdit();
    const header = screen.getByRole("heading", { level: 2, name: "Events" });
    fireEvent.pointerDown(header, { button: 0, pointerId: 1, clientX: 5, clientY: 5 });
    expect(screen.getByTestId("drop-outline")).toBeInTheDocument();
    fireEvent.pointerCancel(header, { pointerId: 1 });
    expect(screen.queryByTestId("drop-outline")).not.toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "Options for Events" }), { button: 0, pointerId: 2, clientX: 5, clientY: 5 });
    expect(screen.queryByTestId("drop-outline")).not.toBeInTheDocument();
  });
});

describe("per-widget menu is non-modal", () => {
  it("leaves the rest of the page visible to assistive technology and portals inside the dashboard section", async () => {
    mount();
    const user = await enterEdit();
    const menu = await openMenu(user, "Events");
    const section = screen.getByRole("region", { name: "Main dashboard" });
    expect(section).toContainElement(menu);
    expect(section.closest("[aria-hidden]")).toBeNull();
    // Radix marks what a modal hid with data-aria-hidden; a non-modal menu hides nothing.
    expect(document.querySelectorAll("[data-aria-hidden]")).toHaveLength(0);
    expect(screen.getByRole("group", { name: "Edit tools" })).toBeVisible();
  });

  it("closes on Escape and returns focus to its button", async () => {
    mount();
    const user = await enterEdit();
    await openMenu(user, "Events");
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Options for Events" })).toHaveFocus();
  });

  it("closes on a click outside it without changing the layout", async () => {
    mount();
    const user = await enterEdit();
    await openMenu(user, "Events");
    await user.click(document.body);
    await waitFor(() => {
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    });
    expect(size("events-2")).toBe("5x10");
  });

  it("moves between items with the arrow keys, skipping a disabled one, and selects with Enter", async () => {
    mount();
    const user = await enterEdit();
    // Needs me is 7×10, so L is disabled and Arrow keys skip it.
    const menu = await openMenu(user, "Needs me");
    await user.keyboard("{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: /^S ·/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "Pin" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await expectLive("Needs me pinned.");
  });

  it("announces a menu action straight away", async () => {
    mount();
    const user = await enterEdit();
    const menu = await openMenu(user, "Events");
    await user.click(within(menu).getByRole("menuitem", { name: /^S ·/ }));
    expect(live()).toHaveTextContent("Events resized to 3×5.");
  });
});

describe("reset", () => {
  it("opens a confirm dialog offering the four templates, with Apply disabled until one is chosen", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    const dialog = await screen.findByRole("dialog", { name: "Reset this dashboard" });
    expect(within(dialog).getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["main", "student", "work", "minimal"]);
    expect(within(dialog).getByRole("button", { name: "Apply template" })).toBeDisabled();
  });

  it.each<[TemplateName, string]>([
    ["main", "Main"],
    ["student", "Student"],
    ["work", "Work"],
  ])("applying %s replaces the layout, announces it, and Undo brings the old one back", async (template, label) => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: new RegExp(label) }));
    await user.click(within(dialog).getByRole("button", { name: "Apply template" }));
    expect(widgetIds()).toEqual(DEFAULT_LAYOUTS[template].items.map((i) => i.id));
    await expectLive(`Applied the ${label} template: ${String(DEFAULT_LAYOUTS[template].items.length)} widgets.`);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Reset" })).toHaveFocus();
    });
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(widgetIds()).toEqual(["needs_me-1", "events-2"]);
  });

  it("applying Minimal to the Main layout replaces it with the two Minimal widgets", async () => {
    mount(DEFAULT_LAYOUTS.main);
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: /Minimal/ }));
    await user.click(within(dialog).getByRole("button", { name: "Apply template" }));
    expect(widgetIds()).toEqual(["needs_me-1", "events-2"]);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(widgetIds()).toEqual(DEFAULT_LAYOUTS.main.items.map((i) => i.id));
  });

  it("applying the template that is already shown changes nothing and says so", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: /Minimal/ }));
    await user.click(within(dialog).getByRole("button", { name: "Apply template" }));
    await expectLive("The layout already matches the Minimal template.");
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
  });

  it("Cancel and Escape change nothing and return focus to Reset", async () => {
    mount();
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Reset" })).toHaveFocus();
    });
    await user.click(screen.getByRole("button", { name: "Reset" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(widgetIds()).toEqual(["needs_me-1", "events-2"]);
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
  });
});

describe("export", () => {
  it("downloads the dashboard's stored layout document under the dashboard's name and announces it", async () => {
    mount(DEFAULT_LAYOUTS.minimal, "School year");
    const user = await enterEdit();
    await user.click(screen.getByRole("button", { name: "Export" }));
    expect(downloadText).toHaveBeenCalledTimes(1);
    const [filename, content] = vi.mocked(downloadText).mock.calls[0] ?? [];
    expect(filename).toBe("command-center-School-year-layout.json");
    expect(JSON.parse(content ?? "")).toMatchObject({ version: 1, items: [{ id: "needs_me-1" }, { id: "events-2" }] });
    await expectLive("Exported command-center-School-year-layout.json.");
  });

  it("exports what is on screen, including an unsaved change", async () => {
    mount();
    const user = await enterEdit();
    const menu = await openMenu(user, "Events");
    await user.click(within(menu).getByRole("menuitem", { name: /^S ·/ }));
    await user.click(screen.getByRole("button", { name: "Export" }));
    const doc = JSON.parse(vi.mocked(downloadText).mock.calls[0]?.[1] ?? "") as { items: { id: string; w: number; h: number }[] };
    expect(doc.items.find((i) => i.id === "events-2")).toMatchObject({ w: 3, h: 5 });
  });
});
