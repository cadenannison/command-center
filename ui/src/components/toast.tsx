import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "./ui/button";

/** How long a toast stays when nobody is on it (decision 0402). Hover and focus inside it hold it open. */
export const TOAST_MS = 6000;

export interface ToastAction {
  /** Visible text: the button's name comes from it. */
  readonly label: string;
  readonly run: () => void;
}

export interface ToastOptions {
  /** Fixed text. Never server text. */
  readonly message: string;
  /** The item's title, shown after the message and marked data-sensitive (decision 0396). */
  readonly subject?: string;
  readonly action?: ToastAction;
  /** An error is announced assertively; everything else politely. */
  readonly tone?: "info" | "error";
  /** Move focus to the action: set when a keyboard user caused the toast, so Undo is one Tab away, not at the end of the page. */
  readonly focusAction?: boolean;
}

export interface ToastApi {
  readonly show: (options: ToastOptions) => void;
  readonly dismiss: () => void;
}

const NOOP: ToastApi = { show: () => {}, dismiss: () => {} };
const ToastContext = createContext<ToastApi>(NOOP);

/** Without a provider (a widget in a test, the gallery) a toast is silently dropped. */
export function useToast(): ToastApi {
  return useContext(ToastContext);
}

interface Live extends ToastOptions {
  readonly id: number;
}

/** One toast at a time. A new one replaces the old and cancels its timer, so a stale message never wins (decision 0388).
 *  Render it inside <main>: the live regions and the Undo button belong to the page's landmark. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Live | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const counter = useRef(0);
  const actionRef = useRef<HTMLButtonElement>(null);

  const cancelTimer = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const dismiss = useCallback(() => {
    cancelTimer();
    // Focus inside the toast would fall to <body> when it unmounts: park it on the page landmark instead.
    const box = document.querySelector<HTMLElement>("[data-testid='toast']");
    if (box?.contains(document.activeElement)) {
      const main = box.closest<HTMLElement>("main");
      if (main) {
        main.tabIndex = -1;
        main.focus({ preventScroll: true });
      }
    }
    setToast(null);
  }, [cancelTimer]);
  const arm = useCallback(() => {
    cancelTimer();
    timer.current = setTimeout(() => {
      timer.current = null;
      setToast(null);
    }, TOAST_MS);
  }, [cancelTimer]);
  const show = useCallback(
    (options: ToastOptions) => {
      counter.current += 1;
      setToast({ ...options, id: counter.current });
      arm();
    },
    [arm],
  );
  useEffect(() => cancelTimer, [cancelTimer]);

  const focusId = toast?.focusAction ? toast.id : null;
  useEffect(() => {
    if (focusId !== null) actionRef.current?.focus();
  }, [focusId]);

  const api = useMemo<ToastApi>(() => ({ show, dismiss }), [show, dismiss]);
  const error = toast?.tone === "error";
  const repeatMark = toast && toast.id % 2 === 1 ? " " : "";
  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* The live regions stay mounted so a screen reader hears each change; the visible box repeats the text, hidden from it. */}
      {/* An odd-numbered toast ends in a no-break space, so the same text twice in a row is a real change and is read again. */}
      <div role="status" className="sr-only">
        {toast && !error ? `${toast.message}${toast.subject ? ` ${toast.subject}` : ""}${repeatMark}` : ""}
      </div>
      <div role="alert" className="sr-only">
        {toast && error ? `${toast.message}${repeatMark}` : ""}
      </div>
      {toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4">
          <div
            key={toast.id}
            data-testid="toast"
            className="pointer-events-auto flex max-w-full items-center gap-3 rounded-control border border-edge bg-pop px-4 py-2 text-fg"
            onPointerEnter={cancelTimer}
            onPointerLeave={arm}
            onFocus={cancelTimer}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) arm();
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") dismiss();
            }}
          >
            <span aria-hidden="true" className="min-w-0 truncate">
              {toast.message}
              {toast.subject && (
                <>
                  {" "}
                  <span data-sensitive>{toast.subject}</span>
                </>
              )}
            </span>
            {toast.action && (
              <Button
                ref={actionRef}
                size="sm"
                variant="outline"
                onClick={() => {
                  const run = toast.action?.run;
                  dismiss();
                  run?.();
                }}
              >
                {toast.action.label}
              </Button>
            )}
          </div>
        </div>
      )}
    </ToastContext.Provider>
  );
}
