import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TOAST_MS, ToastProvider, useToast, type ToastOptions } from "./toast";

afterEach(() => {
  vi.useRealTimers();
});

function Probe({ options, second }: { options: ToastOptions; second?: ToastOptions }) {
  const toast = useToast();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          toast.show(options);
        }}
      >
        Open
      </button>
      {second && (
        <button
          type="button"
          onClick={() => {
            toast.show(second);
          }}
        >
          Open second
        </button>
      )}
    </>
  );
}

function mount(options: ToastOptions, second?: ToastOptions) {
  render(
    <ToastProvider>
      <Probe options={options} {...(second ? { second } : {})} />
    </ToastProvider>,
  );
}

describe("toast", () => {
  it("announces politely, shows the message and runs the action once, then closes", async () => {
    const run = vi.fn();
    mount({ message: "Dismissed.", subject: "Essay", action: { label: "Undo", run } });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("status")).toHaveTextContent("Dismissed. Essay");
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(run).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  it("marks the item title data-sensitive and keeps the message outside the mask", async () => {
    mount({ message: "Dismissed.", subject: "Essay" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Open" }));
    const toast = screen.getByTestId("toast");
    expect(toast.querySelector("[data-sensitive]")).toHaveTextContent("Essay");
    expect(toast).toHaveTextContent("Dismissed.");
  });

  it("announces an error assertively", async () => {
    mount({ message: "Could not dismiss it. Try again.", tone: "error" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not dismiss it. Try again.");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("closes by itself after the delay", () => {
    vi.useFakeTimers();
    mount({ message: "Dismissed.", action: { label: "Undo", run: vi.fn() } });
    act(() => {
      screen.getByRole("button", { name: "Open" }).click();
    });
    expect(screen.getByTestId("toast")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(TOAST_MS - 1);
    });
    expect(screen.getByTestId("toast")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("a newer toast replaces the old one and the old timer does not close it (decision 0388)", () => {
    vi.useFakeTimers();
    mount({ message: "Dismissed." }, { message: "Marked done." });
    act(() => {
      screen.getByRole("button", { name: "Open" }).click();
    });
    act(() => {
      vi.advanceTimersByTime(TOAST_MS - 1000);
    });
    act(() => {
      screen.getByRole("button", { name: "Open second" }).click();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Marked done.");
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    // The first toast's timer would have fired by now; the second has a full delay of its own.
    expect(screen.getByTestId("toast")).toHaveTextContent("Marked done.");
    expect(screen.getByRole("status")).toHaveTextContent("Marked done.");
  });

  it("stays open while the pointer is on it and while focus is inside it", () => {
    vi.useFakeTimers();
    mount({ message: "Dismissed.", action: { label: "Undo", run: vi.fn() } });
    act(() => {
      screen.getByRole("button", { name: "Open" }).click();
    });
    const toast = screen.getByTestId("toast");
    act(() => {
      toast.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
      screen.getByRole("button", { name: "Undo" }).focus();
    });
    act(() => {
      vi.advanceTimersByTime(TOAST_MS * 3);
    });
    expect(screen.getByTestId("toast")).toBeInTheDocument();
  });

  it("is reachable by keyboard: focusAction moves focus to the action, and Escape closes", async () => {
    mount({ message: "Dismissed.", action: { label: "Undo", run: vi.fn() }, focusAction: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("button", { name: "Undo" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  it("returns focus to <main> when Undo closes the toast under focus, not to <body>", async () => {
    render(
      <main>
        <ToastProvider>
          <Probe options={{ message: "Dismissed.", action: { label: "Undo", run: vi.fn() }, focusAction: true }} />
        </ToastProvider>
      </main>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("button", { name: "Undo" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("changes the live region's content when the same text is shown twice in a row, so it is read again", async () => {
    mount({ message: "Dismissed.", subject: "Essay" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    const first = screen.getByRole("status").textContent;
    await user.click(screen.getByRole("button", { name: "Open" }));
    const second = screen.getByRole("status").textContent;
    expect(first).not.toBe(second);
    expect(screen.getByRole("status")).toHaveTextContent("Dismissed. Essay");
  });

  it("does not take focus when focusAction is not set", async () => {
    mount({ message: "Dismissed.", action: { label: "Undo", run: vi.fn() } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("button", { name: "Undo" })).not.toHaveFocus();
  });

  it("is a no-op without a provider", async () => {
    render(<Probe options={{ message: "Dismissed." }} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Open" }));
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });
});
