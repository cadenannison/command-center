import { Dialog } from "radix-ui";
import { useState } from "react";
import { Button } from "../../components/ui/button";
import { DEFAULT_LAYOUTS, getWidget, type TemplateName } from "../../layout";
import { DialogShell } from "./dialog-parts";

export const TEMPLATES: readonly { readonly name: TemplateName; readonly label: string }[] = [
  { name: "main", label: "Main" },
  { name: "student", label: "Student" },
  { name: "work", label: "Work" },
  { name: "minimal", label: "Minimal" },
];

const contents = (name: TemplateName): string =>
  DEFAULT_LAYOUTS[name].items.map((i) => getWidget(i.widgetId)?.title ?? i.widgetId).join(", ");

export interface ResetDialogProps {
  readonly dashboardName: string;
  readonly onApply: (name: TemplateName, label: string) => void;
}

/** Reset: pick one of the four templates and confirm. Applying it replaces the layout and can be undone. */
export function ResetDialog({ dashboardName, onApply }: ResetDialogProps) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<TemplateName | null>(null);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setChosen(null);
      }}
    >
      <Dialog.Trigger asChild>
        <Button variant="outline">Reset</Button>
      </Dialog.Trigger>
      <DialogShell
        title="Reset this dashboard"
        description={`Replace the layout of ${dashboardName} with a template. You can undo it afterwards.`}
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="sr-only">Template</legend>
          {TEMPLATES.map(({ name, label }) => (
            <label key={name} className="flex cursor-pointer items-start gap-3 rounded-control border border-line p-3">
              <input
                type="radio"
                name="reset-template"
                value={name}
                checked={chosen === name}
                onChange={() => {
                  setChosen(name);
                }}
                className="mt-1"
              />
              <span>
                <span className="block font-medium">{label}</span>
                <span className="block text-caption text-muted">{contents(name)}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="flex justify-end gap-2">
          <Dialog.Close asChild>
            <Button variant="outline">Cancel</Button>
          </Dialog.Close>
          <Button
            variant="destructive"
            disabled={chosen === null}
            onClick={() => {
              const template = TEMPLATES.find((t) => t.name === chosen);
              if (!template) return;
              setOpen(false);
              setChosen(null);
              onApply(template.name, template.label);
            }}
          >
            Apply template
          </Button>
        </div>
      </DialogShell>
    </Dialog.Root>
  );
}
