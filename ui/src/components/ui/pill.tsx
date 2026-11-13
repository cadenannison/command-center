import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

/** Round to a whole number and keep it in 1 to 10. NaN has no honest number to print, so it gives null. */
export function normalizePriority(value: number): number | null {
  if (Number.isNaN(value)) return null;
  return Math.min(10, Math.max(1, Math.round(value)));
}

/** Priority 1 to 10. The fill comes from data-priority (tokens.css); the text is always the dark pill ink
 *  and the number is always printed, so color is never the only signal (spec, Tokens). */
export function Pill({ priority, className, ...props }: { priority: number } & Omit<ComponentProps<"span">, "children">) {
  const value = normalizePriority(priority);
  if (value === null) return null;
  return (
    <span
      data-priority={value}
      className={cn(
        "tnum inline-flex h-[22px] min-w-[30px] flex-none items-center justify-center rounded-pill bg-(--cc-p) px-2 font-display text-caption font-bold text-(color:--cc-pill-text)",
        className,
      )}
      {...props}
    >
      <span className="sr-only">Priority </span>
      {value}
    </span>
  );
}
