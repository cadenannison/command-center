import { ChevronDown } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { useState } from "react";
import { Button } from "../../components/ui/button";
import { useItemActions, type ItemRef, type SnoozePreset } from "./use-item-actions";

const PRESETS: readonly { readonly preset: SnoozePreset; readonly label: string }[] = [
  { preset: "later_today", label: "Later today" },
  { preset: "tomorrow_morning", label: "Tomorrow morning" },
  { preset: "next_week", label: "Next week" },
];

const MENU_ITEM =
  "flex min-h-8 cursor-default select-none items-center rounded-control px-3 py-1 outline-none data-[disabled]:opacity-60 data-[highlighted]:bg-chip";

/** Done, Dismiss and Snooze for one row, shown in its expanded state (decision 0402). Snooze opens a non-modal menu
 *  portaled into <main>. Every button is named by its visible text. */
export function RowActions({ item }: { item: ItemRef }) {
  const actions = useItemActions();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return (
    <div ref={setAnchor} role="group" aria-label="Actions" className="flex flex-wrap items-center gap-2 pb-2 pl-2">
      <Button
        size="sm"
        variant="outline"
        disabled={actions.busy}
        onClick={() => {
          actions.done(item);
        }}
      >
        Done
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={actions.busy}
        onClick={() => {
          actions.dismiss(item);
        }}
      >
        Dismiss
      </Button>
      <DropdownMenu.Root modal={false}>
        <DropdownMenu.Trigger asChild>
          <Button size="sm" variant="outline" disabled={actions.busy}>
            Snooze
            <ChevronDown size={14} aria-hidden="true" />
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal container={anchor?.closest("main") ?? null}>
          <DropdownMenu.Content
            align="start"
            sideOffset={4}
            className="z-50 min-w-44 rounded-control border border-edge bg-pop p-1 text-fg"
          >
            {PRESETS.map(({ preset, label }) => (
              <DropdownMenu.Item
                key={preset}
                className={MENU_ITEM}
                onSelect={() => {
                  actions.snooze(item, preset);
                }}
              >
                {label}
              </DropdownMenu.Item>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
