import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizePriority, Pill } from "./pill";

describe("Pill", () => {
  it.each([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])("prints the number %i and picks its color", (n) => {
    const { container } = render(<Pill priority={n} />);
    const pill = container.querySelector("[data-priority]");
    expect(pill).toHaveTextContent(`Priority ${String(n)}`);
    expect(pill).not.toHaveAttribute("aria-label");
    expect(pill).toHaveAttribute("data-priority", String(n));
  });

  it("always uses the dark pill ink, never a theme text color", () => {
    const { container } = render(<Pill priority={9} />);
    const pill = container.querySelector<HTMLElement>("[data-priority]");
    expect(pill?.className).toContain("text-(color:--cc-pill-text)");
    expect(pill?.className).toContain("bg-(--cc-p)");
    expect(pill?.className).not.toMatch(/text-(fg|muted|subtle)/);
  });

  it("keeps out-of-range numbers inside 1 to 10 and prints the number it shows", () => {
    const { container } = render(<Pill priority={14} />);
    expect(container.querySelector("[data-priority]")).toHaveTextContent("Priority 10");
    expect(normalizePriority(0)).toBe(1);
    expect(normalizePriority(3.6)).toBe(4);
  });

  it("renders nothing when there is no number to print", () => {
    const { container } = render(<Pill priority={Number.NaN} />);
    expect(container).toBeEmptyDOMElement();
  });
});
