import { useEffect, useRef } from "react";

/** A text field, select or editable region: Ctrl or Cmd Z belongs to it there (the browser's own undo). */
export function inTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return target.closest("input, textarea, select, [contenteditable='true'], [contenteditable='']") !== null;
}

export type ShortcutAction = "undo" | "redo";

/** Ctrl or Cmd Z is undo, with Shift redo. Anything else, a held key, or a key another handler already took is none. */
export function shortcutFor(event: KeyboardEvent): ShortcutAction | null {
  if (event.defaultPrevented || event.repeat || event.altKey) return null;
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return null;
  return event.shiftKey ? "redo" : "undo";
}

/** An open dialog or menu owns the keyboard, so the shortcut waits until it closes. */
export function insideOverlay(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("[role='dialog'], [role='alertdialog'], [role='menu']") !== null;
}

export interface ShortcutHandlers {
  readonly enabled: boolean;
  readonly onUndo: () => void;
  readonly onRedo: () => void;
}

/** Registers one keydown listener only while `enabled` (shortcuts setting on and edit mode on). When it is off
 *  nothing is registered at all, so there is no handler to obstruct anything. */
export function useUndoRedoShortcuts({ enabled, onUndo, onRedo }: ShortcutHandlers): void {
  const latest = useRef({ onUndo, onRedo });
  useEffect(() => {
    latest.current = { onUndo, onRedo };
  });
  useEffect(() => {
    if (!enabled) return;
    const listener = (event: KeyboardEvent) => {
      const action = shortcutFor(event);
      if (!action || inTextField(event.target) || insideOverlay(event.target)) return;
      event.preventDefault();
      if (action === "undo") latest.current.onUndo();
      else latest.current.onRedo();
    };
    document.addEventListener("keydown", listener);
    return () => {
      document.removeEventListener("keydown", listener);
    };
  }, [enabled]);
}

export const SHORTCUT_HINT_PC = "Shortcuts: Ctrl+Z undo, Ctrl+Shift+Z redo.";
export const SHORTCUT_HINT_MAC = "Shortcuts: ⌘Z undo, ⌘⇧Z redo.";

export function shortcutHint(): string {
  return /Mac|iPhone|iPad/.test(globalThis.navigator.userAgent) ? SHORTCUT_HINT_MAC : SHORTCUT_HINT_PC;
}
