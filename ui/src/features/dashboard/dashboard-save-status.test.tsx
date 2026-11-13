import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardView } from "./dashboard-view";
import { dashboardOf, installGridEnv, json } from "./test-support";

beforeEach(() => {
  installGridEnv(1200, 1400);
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json([]))));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the dashboard save status", () => {
  it("is a polite status region, so a screen reader hears 'Saved' without it moving focus", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DashboardView dashboard={dashboardOf("main", "Main")} flushRef={createRef()} onConflict={() => Promise.resolve(true)} />
      </QueryClientProvider>,
    );
    const status = screen.getByTestId("save-status");
    expect(status).toHaveAttribute("role", "status");
    expect(status).not.toHaveAttribute("aria-live", "assertive");
    expect(status).toBeEmptyDOMElement();
  });
});
