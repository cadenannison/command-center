import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WidgetShell, type WidgetState } from "./widget-shell";

const shell = (state?: WidgetState, extra: Partial<Parameters<typeof WidgetShell>[0]> = {}) =>
  render(
    <WidgetShell title="Tasks" source="canvas" status="Canvas" {...(state ? { state } : {})} {...extra}>
      <p>BODY</p>
    </WidgetShell>,
  );

describe("WidgetShell", () => {
  it("shows the header with the title and quiet status, the body and the footer", () => {
    shell(undefined, { footerRight: "13 open" });
    expect(screen.getByRole("heading", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getAllByText("Canvas").length).toBeGreaterThan(0);
    expect(screen.getByText("BODY")).toBeInTheDocument();
    expect(screen.getByText("13 open")).toBeInTheDocument();
  });

  it("glows in the source color", () => {
    const { container } = shell();
    expect(container.querySelector('[data-source="canvas"]')).toHaveClass("glow");
  });

  it("swaps the status for the tier badge in edit mode", () => {
    shell(undefined, { editing: true, tierBadge: "W2 · H3 · 5×10" });
    expect(screen.getByText("W2 · H3 · 5×10")).toBeInTheDocument();
  });

  it("shows loading as a status with the body hidden", () => {
    shell({ kind: "loading" });
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("BODY")).not.toBeInTheDocument();
  });

  it("shows the empty text", () => {
    shell({ kind: "empty" });
    expect(screen.getByText("All clear. Nothing due.")).toBeInTheDocument();
  });

  it("shows an error as an alert with Retry", async () => {
    const onRetry = vi.fn();
    shell({ kind: "error", source: "Canvas", onRetry });
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach Canvas.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("keeps old data visible when stale and says when it was last synced", () => {
    shell({ kind: "stale", lastSynced: "3 hours ago" });
    expect(screen.getByText("Showing older data. Last synced 3 hours ago.")).toBeInTheDocument();
    expect(screen.getByText("BODY")).toBeInTheDocument();
  });

  it("shows not connected with a Connect button", async () => {
    const onConnect = vi.fn();
    shell({ kind: "not_connected", source: "LearningSuite", onConnect });
    expect(screen.getByText("LearningSuite isn't connected yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(onConnect).toHaveBeenCalledTimes(1);
  });
});
