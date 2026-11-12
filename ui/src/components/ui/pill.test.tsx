import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizePriority, Pill } from "./pill";

describe("Pill", () => {
  it.each([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])("prints the number %i and picks its color", (n) => {
    render(<Pill priority={n} />);
    const pill = screen.getByLabelText(`Priority ${String(n)}`);
    expect(pill).toHaveTextContent(String(n));
    expect(pill).toHaveAttribute("data-priority", String(n));
  });

  it("always uses the dark pill ink, never a theme text color", () => {
    render(<Pill priority={9} />);
    const pill = screen.getByLabelText("Priority 9");
    expect(pill.className).toContain("text-(color:--cc-pill-text)");
    expect(pill.className).toContain("bg-(--cc-p)");
    expect(pill.className).not.toMatch(/text-(fg|muted|subtle)/);
  });

  it("keeps out-of-range numbers inside 1 to 10 and prints the number it shows", () => {
    render(<Pill priority={14} />);
    expect(screen.getByLabelText("Priority 10")).toHaveTextContent("10");
    expect(normalizePriority(0)).toBe(1);
    expect(normalizePriority(3.6)).toBe(4);
  });

  it("renders nothing when there is no number to print", () => {
    const { container } = render(<Pill priority={Number.NaN} />);
    expect(container).toBeEmptyDOMElement();
  });
});
