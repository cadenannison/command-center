import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardView } from "./dashboard-view";
import { dashboardOf, fireResize, installGridEnv } from "./test-support";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mountView() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DashboardView
        dashboard={dashboardOf("main", "Main")}
        flushRef={createRef()}
        onConflict={() => Promise.resolve(true)}
      />
    </QueryClientProvider>,
  );
}

async function narrow() {
  installGridEnv(900, 1000);
  await act(async () => {
    fireResize();
    await Promise.resolve();
  });
}

describe("widget header in edit mode (decision 0374)", () => {
  it("keeps each title a real heading and puts the drag handle beside it, not around it", async () => {
    installGridEnv(1200, 1400);
    mountView();
    await userEvent.setup().click(screen.getByRole("button", { name: "Edit" }));
    const heading = screen.getByRole("heading", { level: 2, name: "Events" });
    const handle = screen.getByRole("button", { name: /^Move Events, W\d/ });
    expect(handle.contains(heading)).toBe(false);
    expect(heading.closest('[role="button"]')).toBeNull();
    expect(heading.parentElement).toBe(handle.parentElement);
  });

  it("names the handle from its own visible text and keeps the instructions and the word widget in its description", async () => {
    installGridEnv(1200, 1400);
    mountView();
    await userEvent.setup().click(screen.getByRole("button", { name: "Edit" }));
    const handle = screen.getByRole("button", { name: /^Move Events, W\d/ });
    expect(handle).not.toHaveAttribute("aria-label");
    expect(handle).not.toHaveAttribute("aria-roledescription");
    const visible = handle.querySelector("span:not(.sr-only)")?.textContent ?? "";
    expect(visible).toMatch(/^W\d · H\d · 5×10$/);
    expect(handle.textContent).toContain(visible);
    const description = document.getElementById(handle.getAttribute("aria-describedby") ?? "");
    expect(description).toHaveTextContent(/Widget drag handle\. Press Enter to pick up this widget/);
  });
});

describe("narrowing during a keyboard pick-up", () => {
  it("announces, then moves focus to the read-only notice instead of body", async () => {
    installGridEnv(1200, 1400);
    mountView();
    await userEvent.setup().click(screen.getByRole("button", { name: "Edit" }));
    const handle = screen.getByRole("button", { name: /^Move Events, W\d/ });
    handle.focus();
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(handle).toHaveAttribute("aria-pressed", "true");

    await narrow();

    expect(screen.getByTestId("live-region")).toHaveTextContent(/too narrow to edit/);
    const notice = document.getElementById("dashboard-readonly");
    expect(notice).not.toBeNull();
    expect(notice).toHaveFocus();
    expect(document.body).not.toHaveFocus();
  });

  it("does not move focus when nothing was picked up", async () => {
    installGridEnv(1200, 1400);
    mountView();
    await userEvent.setup().click(screen.getByRole("button", { name: "Edit" }));
    await narrow();
    expect(document.getElementById("dashboard-readonly")).not.toHaveFocus();
  });
});
