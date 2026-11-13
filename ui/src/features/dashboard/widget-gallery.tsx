import { Dialog } from "radix-ui";
import { useState, type RefObject } from "react";
import { Button } from "../../components/ui/button";
import type { Layout } from "../../layout";
import { DialogShell } from "./dialog-parts";
import { addBlocker, galleryEntries, sizeText } from "./edit-model";

export interface WidgetGalleryProps {
  readonly layout: Layout;
  readonly onAdd: (widgetId: string) => void;
  /** The Add widget button, so the view can focus it when a removed widget took focus with it. */
  readonly addRef?: RefObject<HTMLButtonElement | null>;
}

/** The Add widget button and the gallery it opens. Rows come from the registry (edit-model.galleryEntries). */
export function WidgetGallery({ layout, onAdd, addRef }: WidgetGalleryProps) {
  const [open, setOpen] = useState(false);
  const entries = galleryEntries();
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button ref={addRef} variant="outline">
          Add widget
        </Button>
      </Dialog.Trigger>
      <DialogShell title="Add a widget" description="Choose a widget. It is added below the others at its default size.">
        <ul className="flex flex-col gap-2">
          {entries.map((entry) => {
            const blocker = addBlocker(layout, entry.widgetId);
            const count = layout.items.filter((i) => i.widgetId === entry.widgetId).length;
            const reasonId = `gallery-reason-${entry.widgetId}`;
            return (
              <li key={entry.widgetId} className="flex items-start gap-3 rounded-control border border-line p-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    {entry.name} <span className="text-caption text-muted">{`· ${entry.kind.replace("_", " ")}`}</span>
                  </p>
                  <p className="text-caption text-muted">{entry.description}</p>
                  <p className="tnum text-caption text-muted">
                    {`Default size ${sizeText(entry.size)}`}
                    {count > 0 ? ` · ${String(count)} on this dashboard` : ""}
                  </p>
                  {blocker && (
                    <p id={reasonId} className="text-caption text-danger">
                      {blocker}
                    </p>
                  )}
                </div>
                <Button
                  size="sm"
                  disabled={blocker !== null}
                  aria-describedby={blocker ? reasonId : undefined}
                  onClick={() => {
                    setOpen(false);
                    onAdd(entry.widgetId);
                  }}
                >
                  {`Add ${entry.name}`}
                </Button>
              </li>
            );
          })}
        </ul>
        <div className="flex justify-end">
          <Dialog.Close asChild>
            <Button variant="outline">Close</Button>
          </Dialog.Close>
        </div>
      </DialogShell>
    </Dialog.Root>
  );
}
