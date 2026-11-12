import type { Layout } from "./types";

export const HISTORY_LIMIT = 100;

export interface HistoryState {
  readonly past: readonly Layout[];
  readonly present: Layout;
  readonly future: readonly Layout[];
  /** What Reset returns to. */
  readonly base: Layout;
}

export type HistoryAction =
  | { readonly type: "apply"; readonly layout: Layout }
  | { readonly type: "undo" }
  | { readonly type: "redo" }
  | { readonly type: "reset" };

export function initHistory(layout: Layout, base: Layout = layout): HistoryState {
  return { past: [], present: layout, future: [], base };
}

const sameLayout = (a: Layout, b: Layout): boolean => a === b || JSON.stringify(a) === JSON.stringify(b);

function commit(state: HistoryState, next: Layout): HistoryState {
  if (sameLayout(state.present, next)) return state;
  return { ...state, past: [...state.past, state.present].slice(-HISTORY_LIMIT), present: next, future: [] };
}

export const canUndo = (s: HistoryState): boolean => s.past.length > 0;
export const canRedo = (s: HistoryState): boolean => s.future.length > 0;

/** Undo, redo and reset-to-default over layouts. A change that equals the present is not recorded; reset is undoable. */
export function historyReducer(state: HistoryState, action: HistoryAction): HistoryState {
  switch (action.type) {
    case "apply":
      return commit(state, action.layout);
    case "reset":
      return commit(state, state.base);
    case "undo": {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return { ...state, past: state.past.slice(0, -1), present: previous, future: [state.present, ...state.future] };
    }
    case "redo": {
      const [next, ...rest] = state.future;
      if (!next) return state;
      return { ...state, past: [...state.past, state.present], present: next, future: rest };
    }
  }
}
