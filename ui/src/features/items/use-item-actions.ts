import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "../../api/client";
import type { components } from "../../api/generated/schema";
import { useToast } from "../../components/toast";

export type SnoozePreset = components["schemas"]["SnoozeRequest"]["preset"];

/** The part of a row the actions need. The title is only shown in the toast, marked data-sensitive. */
export interface ItemRef {
  readonly id: string;
  readonly title: string;
}

export type ItemAction =
  | { readonly kind: "done" | "dismiss" | "restore"; readonly id: string }
  | { readonly kind: "snooze"; readonly id: string; readonly preset: SnoozePreset };

/** Every list an item can be on. A prefix refetches only what is mounted; the rest is marked stale (decision 0402).
 *  Not "summary": only its own Retry asks for it again (decision 0381). */
export const ITEM_QUERY_KEYS = ["tasks", "needs-me", "history", "events", "agenda"] as const;

const ACTION_KEY = ["item-action"] as const;

const SNOOZE_TEXT: Record<SnoozePreset, string> = {
  later_today: "later today",
  tomorrow_morning: "tomorrow morning",
  next_week: "next week",
};

/** Fixed texts: the server's error text is never shown. */
const FAILED: Record<ItemAction["kind"], string> = {
  done: "Could not mark it done. Try again.",
  dismiss: "Could not dismiss it. Try again.",
  snooze: "Could not snooze it. Try again.",
  restore: "Could not undo that. Try again.",
};

/** POST /v1/items/{id}/{done,dismiss,snooze,restore} through the typed client (same origin). */
export function sendItemAction(action: ItemAction): Promise<unknown> {
  const params = { params: { path: { item_id: action.id } } };
  switch (action.kind) {
    case "done":
      return unwrap(() => api.POST("/v1/items/{item_id}/done", params));
    case "dismiss":
      return unwrap(() => api.POST("/v1/items/{item_id}/dismiss", params));
    case "restore":
      return unwrap(() => api.POST("/v1/items/{item_id}/restore", params));
    case "snooze":
      return unwrap(() => api.POST("/v1/items/{item_id}/snooze", { ...params, body: { preset: action.preset } }));
  }
}

/** True when the focused element was reached by keyboard. After a row leaves the list focus falls to the page,
 *  so a keyboard user's toast takes focus; a mouse user's does not. */
function keyboardFocus(): boolean {
  try {
    return document.activeElement?.matches(":focus-visible") ?? false;
  } catch {
    return false;
  }
}

export interface ItemActions {
  readonly done: (item: ItemRef) => void;
  readonly dismiss: (item: ItemRef) => void;
  readonly snooze: (item: ItemRef, preset: SnoozePreset) => void;
  /** Restore clears done, dismissed and snoozed. Its toast has no Undo of its own. */
  readonly restore: (item: ItemRef, onRestored?: () => void) => void;
  /** An item action is in flight anywhere on the page: disable every button that would start another. */
  readonly busy: boolean;
}

/** Done, Dismiss, Snooze and Restore for one item, with the shared Undo toast. On success every list is refetched in
 *  place (no reset of what the user is looking at, 0375). A failure shows a fixed message and changes nothing. */
export function useItemActions(): ItemActions {
  const client = useQueryClient();
  const toast = useToast();
  const mutation = useMutation({
    mutationKey: ACTION_KEY,
    mutationFn: sendItemAction,
    // Options-level, so it still runs when the row that started the action has already left the list.
    // The toast does not wait for the refetches.
    onSuccess: () => {
      for (const key of ITEM_QUERY_KEYS) void client.invalidateQueries({ queryKey: [key] });
    },
  });

  // Any row's action in flight, not only this hook's: one action at a time (decision 0402).
  const anyPending = useIsMutating({ mutationKey: ACTION_KEY }) > 0;

  const run = (item: ItemRef, action: ItemAction, message: string, undo: boolean, after?: () => void) => {
    const focusAction = keyboardFocus();
    mutation.mutateAsync(action).then(
      () => {
        after?.();
        toast.show({
          message,
          subject: item.title,
          tone: "info",
          focusAction: undo && focusAction,
          ...(undo
            ? {
                action: {
                  label: "Undo",
                  run: () => {
                    restore(item);
                  },
                },
              }
            : {}),
        });
      },
      () => {
        toast.show({
          message: FAILED[action.kind],
          tone: "error",
          action: { label: "Try again", run: () => { run(item, action, message, undo, after); } },
        });
      },
    );
  };
  const restore = (item: ItemRef, onRestored?: () => void) => {
    run(item, { kind: "restore", id: item.id }, "Restored.", false, onRestored);
  };

  return {
    done: (item) => {
      run(item, { kind: "done", id: item.id }, "Marked done.", true);
    },
    dismiss: (item) => {
      run(item, { kind: "dismiss", id: item.id }, "Dismissed.", true);
    },
    snooze: (item, preset) => {
      run(item, { kind: "snooze", id: item.id, preset }, `Snoozed until ${SNOOZE_TEXT[preset]}.`, true);
    },
    restore,
    busy: anyPending,
  };
}
