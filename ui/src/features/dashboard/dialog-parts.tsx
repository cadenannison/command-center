import { Dialog } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

/** The shared look of the edit-mode dialogs: Radix gives the focus trap, Escape, aria-modal and focus return. */
export function DialogShell({
  title,
  description,
  className,
  children,
  ...props
}: Omit<ComponentProps<typeof Dialog.Content>, "title"> & { title: string; description: string }) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
      <Dialog.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(92vw,34rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 overflow-y-auto rounded-widget border border-edge bg-pop p-5 text-fg",
          className,
        )}
        {...props}
      >
        <Dialog.Title className="font-display text-lg font-semibold">{title}</Dialog.Title>
        <Dialog.Description className="text-muted">{description}</Dialog.Description>
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}
