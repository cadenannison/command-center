import type { RefObject } from "react";
import { Button } from "../../components/ui/button";
import type { Layout, TemplateName } from "../../layout";
import { ResetDialog } from "./reset-dialog";
import { WidgetGallery } from "./widget-gallery";

export interface EditToolbarProps {
  readonly layout: Layout;
  readonly dashboardName: string;
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  readonly onAdd: (widgetId: string) => void;
  readonly onUndo: () => void;
  readonly onRedo: () => void;
  readonly onReset: (name: TemplateName, label: string) => void;
  readonly onExport: () => void;
  readonly onDone: () => void;
  readonly addRef: RefObject<HTMLButtonElement | null>;
}

/** The edit-mode tools. The view renders it only in edit mode at 12 columns (decision 0361). */
export function EditToolbar(props: EditToolbarProps) {
  return (
    <div role="group" aria-label="Edit tools" className="flex flex-wrap items-center gap-2">
      <WidgetGallery layout={props.layout} onAdd={props.onAdd} addRef={props.addRef} />
      <Button variant="outline" disabled={!props.canUndo} onClick={props.onUndo}>
        Undo
      </Button>
      <Button variant="outline" disabled={!props.canRedo} onClick={props.onRedo}>
        Redo
      </Button>
      <ResetDialog dashboardName={props.dashboardName} onApply={props.onReset} />
      <Button variant="outline" onClick={props.onExport}>
        Export
      </Button>
      <Button onClick={props.onDone}>Done</Button>
    </div>
  );
}
