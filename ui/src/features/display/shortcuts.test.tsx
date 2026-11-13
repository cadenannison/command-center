import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { inTextField, insideOverlay, shortcutFor, shortcutHint, useUndoRedoShortcuts } from "./shortcuts";

function Probe({ enabled, onUndo, onRedo }: { enabled: boolean; onUndo: () => void; onRedo: () => void }) {
  useUndoRedoShortcuts({ enabled, onUndo, onRedo });
  return (
    <div>
      <input aria-label="field" />
      <textarea aria-label="area" />
      <select aria-label="pick">
        <option>a</option>
      </select>
      <div role="dialog" aria-label="box">
        <button>inside</button>
      </div>
      <div role="menu" aria-label="menu">
        <button>menu item</button>
      </div>
      <button>plain</button>
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

const key = (init: KeyboardEventInit) => new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });

describe("shortcutFor", () => {
  it("maps Ctrl or Cmd Z to undo and with Shift to redo", () => {
    expect(shortcutFor(key({ key: "z", ctrlKey: true }))).toBe("undo");
    expect(shortcutFor(key({ key: "z", metaKey: true }))).toBe("undo");
    expect(shortcutFor(key({ key: "Z", ctrlKey: true, shiftKey: true }))).toBe("redo");
    expect(shortcutFor(key({ key: "z", metaKey: true, shiftKey: true }))).toBe("redo");
  });

  it("ignores other keys, bare Z, Alt, a held key and a key already handled", () => {
    expect(shortcutFor(key({ key: "y", ctrlKey: true }))).toBeNull();
    expect(shortcutFor(key({ key: "z" }))).toBeNull();
    expect(shortcutFor(key({ key: "z", ctrlKey: true, altKey: true }))).toBeNull();
    expect(shortcutFor(key({ key: "z", ctrlKey: true, repeat: true }))).toBeNull();
    const taken = key({ key: "z", ctrlKey: true });
    taken.preventDefault();
    expect(shortcutFor(taken)).toBeNull();
  });
});

describe("useUndoRedoShortcuts", () => {
  it("runs undo and redo from the document when enabled", () => {
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    const { getByText } = render(<Probe enabled onUndo={onUndo} onRedo={onRedo} />);
    fireEvent.keyDown(getByText("plain"), { key: "z", ctrlKey: true });
    fireEvent.keyDown(getByText("plain"), { key: "z", metaKey: true, shiftKey: true });
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onRedo).toHaveBeenCalledTimes(1);
  });

  it("never reaches the handler from a text field, a select, a dialog or a menu", () => {
    const onUndo = vi.fn();
    const { getByLabelText, getByText } = render(<Probe enabled onUndo={onUndo} onRedo={vi.fn()} />);
    for (const target of [getByLabelText("field"), getByLabelText("area"), getByLabelText("pick"), getByText("inside"), getByText("menu item")]) {
      fireEvent.keyDown(target, { key: "z", ctrlKey: true });
    }
    expect(onUndo).not.toHaveBeenCalled();
  });

  it("registers no listener at all when disabled", () => {
    const add = vi.spyOn(document, "addEventListener");
    const onUndo = vi.fn();
    const { getByText } = render(<Probe enabled={false} onUndo={onUndo} onRedo={vi.fn()} />);
    expect(add.mock.calls.filter((c) => c[0] === "keydown")).toHaveLength(0);
    fireEvent.keyDown(getByText("plain"), { key: "z", ctrlKey: true });
    expect(onUndo).not.toHaveBeenCalled();
  });

  it("removes its listener when switched off or unmounted, and does not swallow the key then", () => {
    const remove = vi.spyOn(document, "removeEventListener");
    const view = render(<Probe enabled onUndo={vi.fn()} onRedo={vi.fn()} />);
    view.rerender(<Probe enabled={false} onUndo={vi.fn()} onRedo={vi.fn()} />);
    expect(remove.mock.calls.filter((c) => c[0] === "keydown")).toHaveLength(1);
    const event = key({ key: "z", ctrlKey: true });
    document.body.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("calls the latest handler, not the one from when it was registered", () => {
    const first = vi.fn();
    const second = vi.fn();
    const view = render(<Probe enabled onUndo={first} onRedo={vi.fn()} />);
    view.rerender(<Probe enabled onUndo={second} onRedo={vi.fn()} />);
    fireEvent.keyDown(view.getByText("plain"), { key: "z", ctrlKey: true });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});

describe("helpers", () => {
  it("knows a text field and an overlay from a plain button", () => {
    const { getByLabelText, getByText } = render(<Probe enabled={false} onUndo={vi.fn()} onRedo={vi.fn()} />);
    expect(inTextField(getByLabelText("field"))).toBe(true);
    expect(inTextField(getByText("plain"))).toBe(false);
    expect(inTextField(null)).toBe(false);
    expect(insideOverlay(getByText("inside"))).toBe(true);
    expect(insideOverlay(getByText("plain"))).toBe(false);
  });

  it("words the hint for the platform", () => {
    expect(shortcutHint()).toMatch(/^Shortcuts: (Ctrl\+Z undo, Ctrl\+Shift\+Z redo|⌘Z undo, ⌘⇧Z redo)\.$/);
  });
});
