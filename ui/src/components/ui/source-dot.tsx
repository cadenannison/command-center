import type { ComponentProps } from "react";
import { SOURCES, type SourceId } from "../../lib/sources";
import { cn } from "../../lib/utils";

/** A small glowing dot in a source's color. Decorative unless a label is given (the text next to it
 *  should normally name the source). */
export function SourceDot({
  source,
  label,
  className,
  ...props
}: { source: SourceId; label?: string } & Omit<ComponentProps<"span">, "children">) {
  return (
    <span
      data-source={source}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
      className={cn(
        "inline-block size-2.5 flex-none rounded-full bg-[rgb(var(--cc-src))] shadow-[0_0_8px_rgb(var(--cc-src)/0.6)]",
        className,
      )}
      {...props}
    />
  );
}

export function sourceName(source: SourceId): string {
  return SOURCES.find((entry) => entry.id === source)?.name ?? source;
}
