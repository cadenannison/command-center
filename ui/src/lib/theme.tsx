import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** "system" removes data-theme so tokens.css follows prefers-color-scheme. The choice is kept in memory
 *  only: AGENTS.md rule 7 bans localStorage, and persisting it is a later decision (0322). */
export type ThemeChoice = "light" | "dark" | "system";

export const THEME_CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];

export function applyTheme(choice: ThemeChoice, root: HTMLElement = document.documentElement): void {
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

interface ThemeValue {
  theme: ThemeChoice;
  setTheme: (choice: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children, initial = "system" }: { children: ReactNode; initial?: ThemeChoice }) {
  const [theme, setThemeState] = useState<ThemeChoice>(initial);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  const setTheme = useCallback((choice: ThemeChoice) => {
    setThemeState(choice);
  }, []);
  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <ThemeContext value={value}>{children}</ThemeContext>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme needs a ThemeProvider");
  return value;
}
