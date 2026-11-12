import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { applyTheme, ThemeProvider } from "./theme";
import { applyDisplay, clampGlow, clampTextScale, DEFAULT_DISPLAY, DisplayProvider, useDisplay } from "./display";

const root = () => document.documentElement;

afterEach(() => {
  for (const name of ["data-contrast", "data-density", "data-glow", "data-text-scale"]) root().removeAttribute(name);
});

describe("applyDisplay", () => {
  it("writes the default settings as attributes", () => {
    applyDisplay(DEFAULT_DISPLAY);
    expect(root()).not.toHaveAttribute("data-contrast");
    expect(root()).toHaveAttribute("data-density", "comfortable");
    expect(root()).toHaveAttribute("data-glow", "1");
    expect(root()).toHaveAttribute("data-text-scale", "100");
  });

  it("sets high contrast and compact density, and clears contrast again", () => {
    applyDisplay({ highContrast: true, density: "compact", glow: 0, textScale: 150 });
    expect(root()).toHaveAttribute("data-contrast", "high");
    expect(root()).toHaveAttribute("data-density", "compact");
    expect(root()).toHaveAttribute("data-glow", "0");
    expect(root()).toHaveAttribute("data-text-scale", "150");
    applyDisplay({ ...DEFAULT_DISPLAY });
    expect(root()).not.toHaveAttribute("data-contrast");
  });

  it("keeps the theme attribute and the display attributes independent", () => {
    applyTheme("light");
    applyDisplay({ ...DEFAULT_DISPLAY, density: "compact", highContrast: true });
    expect(root()).toHaveAttribute("data-theme", "light");
    applyTheme("system");
    expect(root()).not.toHaveAttribute("data-theme");
    expect(root()).toHaveAttribute("data-density", "compact");
    expect(root()).toHaveAttribute("data-contrast", "high");
  });
});

describe("clamps", () => {
  it("snaps glow to 0.1 steps inside 0 to 1.6", () => {
    expect(clampGlow(-1)).toBe(0);
    expect(clampGlow(3)).toBe(1.6);
    expect(clampGlow(0.74)).toBe(0.7);
    expect(clampGlow(Number.NaN)).toBe(1);
  });

  it("snaps text scale to 5 percent steps inside 90 to 150", () => {
    expect(clampTextScale(85)).toBe(90);
    expect(clampTextScale(200)).toBe(150);
    expect(clampTextScale(102)).toBe(100);
    expect(clampTextScale(Number.NaN)).toBe(100);
  });
});

function Probe() {
  const { display, setDisplay } = useDisplay();
  return (
    <div>
      <button
        onClick={() => {
          setDisplay({ density: display.density === "compact" ? "comfortable" : "compact" });
        }}
      >
        density
      </button>
      <button
        onClick={() => {
          setDisplay({ highContrast: !display.highContrast });
        }}
      >
        contrast
      </button>
    </div>
  );
}

describe("DisplayProvider", () => {
  it("applies attributes on mount and updates them when settings change", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <DisplayProvider>
          <Probe />
        </DisplayProvider>
      </ThemeProvider>,
    );
    expect(root()).toHaveAttribute("data-density", "comfortable");
    await user.click(screen.getByRole("button", { name: "density" }));
    expect(root()).toHaveAttribute("data-density", "compact");
    await user.click(screen.getByRole("button", { name: "contrast" }));
    expect(root()).toHaveAttribute("data-contrast", "high");
    await user.click(screen.getByRole("button", { name: "contrast" }));
    expect(root()).not.toHaveAttribute("data-contrast");
  });
});
