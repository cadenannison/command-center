import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThemeSwitcher } from "../components/theme-switcher";
import { applyTheme, ThemeProvider } from "./theme";

const root = () => document.documentElement;

describe("applyTheme", () => {
  it("sets data-theme for light and dark and removes it for system", () => {
    applyTheme("dark");
    expect(root()).toHaveAttribute("data-theme", "dark");
    applyTheme("light");
    expect(root()).toHaveAttribute("data-theme", "light");
    applyTheme("system");
    expect(root()).not.toHaveAttribute("data-theme");
  });
});

describe("ThemeSwitcher", () => {
  it("follows the system until a choice is made, then switches and returns to system", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeSwitcher />
      </ThemeProvider>,
    );
    expect(root()).not.toHaveAttribute("data-theme");
    expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Dark" }));
    expect(root()).toHaveAttribute("data-theme", "dark");
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Light" }));
    expect(root()).toHaveAttribute("data-theme", "light");

    await user.click(screen.getByRole("button", { name: "System" }));
    expect(root()).not.toHaveAttribute("data-theme");
  });
});
