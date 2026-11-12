import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { cn } from "../../lib/utils";
import { Badge } from "./badge";
import { Button } from "./button";

describe("filled surfaces keep their on-fill text color", () => {
  it("keeps text-accent-fg on a small default Button (the pressed theme button)", () => {
    render(<Button size="sm">Dark</Button>);
    const cls = screen.getByRole("button", { name: "Dark" }).className;
    expect(cls).toContain("bg-accent");
    expect(cls).toContain("text-accent-fg");
    expect(cls).toContain("text-caption");
  });

  it("keeps text-danger-fg on a small destructive Button", () => {
    render(<Button size="sm" variant="destructive">Remove</Button>);
    expect(screen.getByRole("button").className).toContain("text-danger-fg");
  });

  it("pairs every filled Badge with its foreground", () => {
    render(
      <>
        <Badge variant="accent">Now</Badge>
        <Badge variant="destructive">Overdue</Badge>
      </>,
    );
    expect(screen.getByText("Now").className).toContain("text-accent-fg");
    expect(screen.getByText("Overdue").className).toContain("text-danger-fg");
  });

  it("cn still lets a later text color replace an earlier one", () => {
    expect(cn("text-fg", "text-accent-fg")).toBe("text-accent-fg");
    expect(cn("text-accent-fg", "text-caption")).toBe("text-accent-fg text-caption");
  });
});
