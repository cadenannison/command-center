import { THEME_CHOICES, useTheme, type ThemeChoice } from "../lib/theme";
import { Button } from "./ui/button";

const LABELS: Record<ThemeChoice, string> = { light: "Light", dark: "Dark", system: "System" };

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();
  return (
    <div role="group" aria-label="Theme" className="flex gap-1">
      {THEME_CHOICES.map((choice) => (
        <Button
          key={choice}
          size="sm"
          variant={theme === choice ? "default" : "outline"}
          aria-pressed={theme === choice}
          onClick={() => {
            setTheme(choice);
          }}
        >
          {LABELS[choice]}
        </Button>
      ))}
    </div>
  );
}
