import { MoreHorizontal } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { LayoutItem, SizePreset } from "../../layout";
import { presetState, sizeText } from "./edit-model";

const SIZES: readonly SizePreset[] = ["S", "M", "L"];
const ITEM =
  "flex min-h-8 cursor-default select-none flex-col justify-center rounded-control px-3 py-1 outline-none data-[disabled]:opacity-60 data-[highlighted]:bg-chip";

export interface WidgetMenuProps {
  readonly item: LayoutItem;
  readonly title: string;
  readonly onRemove: () => void;
  readonly onSize: (name: SizePreset) => void;
  readonly onPin: (pinned: boolean) => void;
  /** Where the menu is portaled: inside the page's landmark, so it is never outside every region. */
  readonly container?: HTMLElement | null;
}

/** The per-widget menu in edit mode: its own button beside the drag handle, never inside the heading. */
export function WidgetMenu({ item, title, onRemove, onSize, onPin, container }: WidgetMenuProps) {
  return (
    // The grid starts a drag on pointer down in the header; none of this menu, which React bubbles through its portal, may.
    <span data-no-drag="">
      <DropdownMenu.Root modal={false}>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            aria-label={`Options for ${title}`}
            className="inline-flex size-7 flex-none items-center justify-center rounded-control text-muted hover:bg-chip focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <MoreHorizontal size={16} aria-hidden="true" />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal container={container ?? null}>
          <DropdownMenu.Content
            align="end"
            sideOffset={4}
            data-no-drag=""
            className="z-50 min-w-48 max-w-72 rounded-control border border-edge bg-pop p-1 text-fg"
          >
            <DropdownMenu.Label className="px-3 py-1 text-caption text-muted">Size</DropdownMenu.Label>
            {SIZES.map((name) => {
              const state = presetState(item, name);
              return (
                <DropdownMenu.Item
                  key={name}
                  disabled={state.disabled}
                  className={ITEM}
                  onSelect={() => {
                    onSize(name);
                  }}
                >
                  <span className="tnum">{`${name} · ${sizeText(state.size)}`}</span>
                  {state.reason && <span className="text-caption text-muted">{state.reason}</span>}
                </DropdownMenu.Item>
              );
            })}
            <DropdownMenu.Separator className="my-1 h-px bg-line" />
            <DropdownMenu.Item
              className={ITEM}
              onSelect={() => {
                onPin(!item.pinned);
              }}
            >
              {item.pinned ? "Unpin" : "Pin"}
            </DropdownMenu.Item>
            <DropdownMenu.Item className={ITEM} onSelect={onRemove}>
              Remove
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </span>
  );
}
