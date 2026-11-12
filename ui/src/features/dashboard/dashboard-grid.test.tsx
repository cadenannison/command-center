import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Layout } from "../../layout";
import { DashboardGrid } from "./dashboard-grid";
import { fireResize, installGridEnv, MINIMAL } from "./test-support";

const COL = (1200 - 14 * 11) / 12 + 14; // pixel pitch of one column at 100 percent
const ROW = 54;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function setup(props: { edit?: boolean; layout?: Layout } = {}) {
  const onChange = vi.fn();
  const onAnnounce = vi.fn();
  render(
    <DashboardGrid
      layout={props.layout ?? MINIMAL}
      zoom={100}
      edit={props.edit ?? true}
      onChange={onChange}
      onAnnounce={onAnnounce}
    />,
  );
  return { onChange, onAnnounce };
}

const header = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name} W\\d`) });
const lastLayout = (fn: ReturnType<typeof vi.fn>): Layout => fn.mock.calls.at(-1)?.[0] as Layout;
const xOf = (layout: Layout, id: string) => layout.items.find((i) => i.id === id)?.x;

describe("DashboardGrid at 12 columns", () => {
  beforeEach(() => {
    installGridEnv(1200, 1400);
  });

  it("places widgets from their cells", () => {
    setup({ edit: false });
    const events = screen.getByTestId("widget-events-2");
    expect(events).toHaveAttribute("data-x", "7");
    expect(screen.getByTestId("dashboard-grid")).toHaveAttribute("data-cols", "12");
  });

  it("shows the tier in each placeholder body", () => {
    setup({ edit: false });
    expect(within(screen.getByTestId("widget-events-2")).getAllByText(/^W\d · H\d · 5×10$/).length).toBeGreaterThan(0);
  });

  it("has no move or resize controls when not editing", () => {
    setup({ edit: false });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("makes each header a focusable button with instructions in edit mode", () => {
    setup();
    const h = header("Events");
    expect(h).toHaveAttribute("tabindex", "0");
    expect(h).toHaveAttribute("aria-pressed", "false");
    expect(document.getElementById(h.getAttribute("aria-describedby") ?? "")).toHaveTextContent(
      /Shift and arrow keys resize/,
    );
  });

  describe("keyboard", () => {
    it("picks up on Enter and announces how to move it", () => {
      const { onAnnounce } = setup();
      fireEvent.keyDown(header("Events"), { key: "Enter" });
      expect(header("Events")).toHaveAttribute("aria-pressed", "true");
      expect(onAnnounce).toHaveBeenLastCalledWith(
        expect.stringMatching(/^Picked up Events at column 8, row 1.*Enter drops, Escape cancels/),
      );
    });

    it("moves with an arrow and announces the new cell", () => {
      const { onAnnounce, onChange } = setup();
      fireEvent.keyDown(header("Events"), { key: "Enter" });
      fireEvent.keyDown(header("Events"), { key: "ArrowLeft" });
      expect(onAnnounce).toHaveBeenLastCalledWith("Events moved to column 7, row 1.");
      expect(screen.getByTestId("widget-events-2")).toHaveAttribute("data-x", "6");
      expect(onChange).not.toHaveBeenCalled();
    });

    it("resizes with Shift and an arrow and announces the size", () => {
      const { onAnnounce } = setup();
      fireEvent.keyDown(header("Needs me"), { key: "Enter" });
      fireEvent.keyDown(header("Needs me"), {
        key: "ArrowLeft",
        shiftKey: true,
      });
      expect(onAnnounce).toHaveBeenLastCalledWith("Needs me resized to 6 wide, 10 tall.");
      expect(screen.getByTestId("widget-needs_me-1")).toHaveAttribute("data-w", "6");
    });

    it("announces a move that cannot happen", () => {
      const { onAnnounce } = setup();
      fireEvent.keyDown(header("Events"), { key: "Enter" });
      fireEvent.keyDown(header("Events"), { key: "ArrowRight" });
      expect(onAnnounce).toHaveBeenLastCalledWith("Events cannot move further: column 8, row 1.");
    });

    it("drops on Enter and reports the layout once", () => {
      const { onAnnounce, onChange } = setup();
      fireEvent.keyDown(header("Events"), { key: "Enter" });
      fireEvent.keyDown(header("Events"), { key: "ArrowLeft" });
      fireEvent.keyDown(header("Events"), { key: "Enter" });
      expect(onChange).toHaveBeenCalledTimes(1);
      expect(xOf(lastLayout(onChange), "events-2")).toBe(6);
      expect(onAnnounce).toHaveBeenLastCalledWith("Dropped Events at column 7, row 1, 5 wide, 10 tall.");
      expect(header("Events")).toHaveAttribute("aria-pressed", "false");
    });

    it("cancels on Escape: the item goes back and nothing is reported", () => {
      const { onAnnounce, onChange } = setup();
      fireEvent.keyDown(header("Events"), { key: "Enter" });
      fireEvent.keyDown(header("Events"), { key: "ArrowLeft" });
      fireEvent.keyDown(header("Events"), { key: "Escape" });
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByTestId("widget-events-2")).toHaveAttribute("data-x", "7");
      expect(onAnnounce).toHaveBeenLastCalledWith("Cancelled. Events is back at column 8, row 1, 5 wide, 10 tall.");
    });

    it("keeps focus on the header through pick up, move and drop", () => {
      setup();
      const h = header("Events");
      h.focus();
      fireEvent.keyDown(h, { key: "Enter" });
      fireEvent.keyDown(h, { key: "ArrowLeft" });
      expect(header("Events")).toBe(h);
      expect(h).toHaveFocus();
      fireEvent.keyDown(h, { key: "Enter" });
      expect(h).toHaveFocus();
    });

    it("drops where it is when focus leaves a picked-up widget", () => {
      const { onChange } = setup();
      const h = header("Events");
      h.focus();
      fireEvent.keyDown(h, { key: "Enter" });
      fireEvent.keyDown(h, { key: "ArrowLeft" });
      h.blur();
      expect(onChange).toHaveBeenCalledTimes(1);
      expect(xOf(lastLayout(onChange), "events-2")).toBe(6);
    });

    it("ignores arrows when nothing is picked up", () => {
      const { onChange, onAnnounce } = setup();
      fireEvent.keyDown(header("Events"), { key: "ArrowLeft" });
      expect(onChange).not.toHaveBeenCalled();
      expect(onAnnounce).not.toHaveBeenCalled();
    });

    it("says a pinned widget cannot move", () => {
      const pinned: Layout = {
        ...MINIMAL,
        items: MINIMAL.items.map((i) => (i.id === "events-2" ? { ...i, pinned: true } : i)),
      };
      const { onAnnounce } = setup({ layout: pinned });
      const h = screen.getByRole("button", { name: /^Events W\d/ });
      fireEvent.keyDown(h, { key: "Enter" });
      fireEvent.keyDown(h, { key: "ArrowLeft" });
      expect(onAnnounce).toHaveBeenLastCalledWith("Events is pinned and cannot move or resize.");
    });
  });

  describe("pointer", () => {
    const drag = (el: Element, from: [number, number], to: [number, number]) => {
      fireEvent.pointerDown(el, {
        pointerId: 1,
        button: 0,
        clientX: from[0],
        clientY: from[1],
      });
      fireEvent.pointerMove(el, {
        pointerId: 1,
        clientX: to[0],
        clientY: to[1],
      });
    };

    it("shows a snapped drop outline while a header is dragged", () => {
      setup();
      drag(header("Events"), [800, 20], [800 - COL, 20]);
      expect(screen.getByTestId("drop-outline")).toBeInTheDocument();
    });

    it("moves a widget by the cells the pointer travelled when released", () => {
      const { onChange, onAnnounce } = setup();
      const h = header("Events");
      drag(h, [800, 20], [800 - COL - 10, 20]);
      fireEvent.pointerUp(h, { pointerId: 1 });
      expect(xOf(lastLayout(onChange), "events-2")).toBe(6);
      expect(onAnnounce).toHaveBeenLastCalledWith("Dropped Events at column 7, row 1, 5 wide, 10 tall.");
      expect(screen.queryByTestId("drop-outline")).not.toBeInTheDocument();
    });

    it("moves down by whole rows", () => {
      const { onChange } = setup();
      const h = header("Events");
      drag(h, [800, 20], [800, 20 + ROW * 2]);
      fireEvent.pointerUp(h, { pointerId: 1 });
      expect(lastLayout(onChange).items.find((i) => i.id === "events-2")?.y).toBe(2);
    });

    it("resizes from the bottom-right corner", () => {
      const { onChange } = setup();
      const corner = within(screen.getByTestId("widget-needs_me-1")).getByTestId("handle-se");
      drag(corner, [500, 500], [500 - COL, 500 + ROW]);
      fireEvent.pointerUp(corner, { pointerId: 1 });
      expect(lastLayout(onChange).items.find((i) => i.id === "needs_me-1")).toMatchObject({ w: 6, h: 11 });
    });

    it("resizes width only from the right edge", () => {
      const { onChange } = setup();
      const edge = within(screen.getByTestId("widget-needs_me-1")).getByTestId("handle-e");
      drag(edge, [500, 100], [500 - COL, 100 + ROW * 3]);
      fireEvent.pointerUp(edge, { pointerId: 1 });
      expect(lastLayout(onChange).items.find((i) => i.id === "needs_me-1")).toMatchObject({ w: 6, h: 10 });
    });

    it("resizes height only from the bottom edge", () => {
      const { onChange } = setup();
      const edge = within(screen.getByTestId("widget-needs_me-1")).getByTestId("handle-s");
      drag(edge, [100, 500], [100 + COL * 3, 500 + ROW]);
      fireEvent.pointerUp(edge, { pointerId: 1 });
      expect(lastLayout(onChange).items.find((i) => i.id === "needs_me-1")).toMatchObject({ w: 7, h: 11 });
    });

    it("cancels a drag on Escape", () => {
      const { onChange } = setup();
      const h = header("Events");
      drag(h, [800, 20], [800 - COL, 20]);
      fireEvent.keyDown(window, { key: "Escape" });
      fireEvent.pointerUp(h, { pointerId: 1 });
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.queryByTestId("drop-outline")).not.toBeInTheDocument();
    });

    it("cancels a drag when the pointer is cancelled", () => {
      const { onChange } = setup();
      const h = header("Events");
      drag(h, [800, 20], [800 - COL, 20]);
      fireEvent.pointerCancel(h, { pointerId: 1 });
      expect(onChange).not.toHaveBeenCalled();
    });

    it("ignores a drag that starts with the secondary button", () => {
      setup();
      fireEvent.pointerDown(header("Events"), {
        pointerId: 1,
        button: 2,
        clientX: 5,
        clientY: 5,
      });
      fireEvent.pointerMove(header("Events"), {
        pointerId: 1,
        clientX: 5 - COL,
        clientY: 5,
      });
      expect(screen.queryByTestId("drop-outline")).not.toBeInTheDocument();
    });

    it("does not offer resize handles on a pinned widget", () => {
      const pinned: Layout = {
        ...MINIMAL,
        items: MINIMAL.items.map((i) => (i.id === "events-2" ? { ...i, pinned: true } : i)),
      };
      setup({ layout: pinned });
      expect(within(screen.getByTestId("widget-events-2")).queryByTestId("handle-se")).not.toBeInTheDocument();
    });
  });
});

describe("DashboardGrid below 12 columns", () => {
  it("is read-only at 8 columns: no pick-up, no handles", () => {
    installGridEnv(900, 1000);
    const { onChange } = setup();
    expect(screen.getByTestId("dashboard-grid")).toHaveAttribute("data-cols", "8");
    expect(screen.getByTestId("dashboard-grid")).toHaveAttribute("data-editing", "false");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("handle-se")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("is read-only at 4 columns", () => {
    installGridEnv(500, 600);
    setup();
    expect(screen.getByTestId("dashboard-grid")).toHaveAttribute("data-cols", "4");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("DashboardGrid when the window narrows mid-edit", () => {
  it("announces that a picked-up widget was put back", () => {
    installGridEnv(1200, 1400);
    const onAnnounce = vi.fn();
    const props = { layout: MINIMAL, zoom: 100, edit: true, onChange: vi.fn(), onAnnounce };
    const { rerender } = render(<DashboardGrid {...props} />);
    fireEvent.keyDown(screen.getByRole("button", { name: /^Events W\d/ }), { key: "Enter" });
    installGridEnv(900, 1000);
    act(() => {
      fireResize();
    });
    rerender(<DashboardGrid {...props} layout={{ ...MINIMAL }} />);
    expect(onAnnounce).toHaveBeenLastCalledWith(expect.stringMatching(/too narrow to edit/));
  });
});
