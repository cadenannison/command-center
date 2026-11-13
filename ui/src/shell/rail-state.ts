import { useCallback, useState } from "react";

export const RAIL_KEY = "cc-rail-collapsed";

// The one place the UI touches localStorage. Card S1 asks for the rail's collapsed flag to persist there; the
// blanket lint ban (AGENTS.md rule 7) exists to keep secrets out of it, and this stores "1" or "0" only
// (decision 0394). Every access is in try/catch so a blocked or full store never breaks the rail.

/** The stored flag; false when nothing is stored or storage is unavailable. */
export function readCollapsed(): boolean {
  try {
    // eslint-disable-next-line no-restricted-syntax -- card S1, decision 0394: a non-secret UI flag
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeCollapsed(collapsed: boolean): void {
  try {
    // eslint-disable-next-line no-restricted-syntax -- card S1, decision 0394: a non-secret UI flag
    localStorage.setItem(RAIL_KEY, collapsed ? "1" : "0");
  } catch {
    // Storage is blocked or full: the rail still collapses for this visit.
  }
}

/** For tests: forget the stored flag. */
export function clearCollapsed(): void {
  try {
    // eslint-disable-next-line no-restricted-syntax -- card S1, decision 0394: a non-secret UI flag
    localStorage.removeItem(RAIL_KEY);
  } catch {
    // Nothing stored.
  }
}

/** Whether the left rail is collapsed, persisted as a per-browser convenience. */
export function useRailCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = useCallback(() => {
    const next = !collapsed;
    setCollapsed(next);
    writeCollapsed(next);
  }, [collapsed]);
  return [collapsed, toggle];
}
