import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// text-caption is our own font-size token (index.css). Without this, tailwind-merge reads it as a text
// color and drops a text-* color given earlier (the pressed theme button lost text-accent-fg, T1b).
const twMerge = extendTailwindMerge({ extend: { classGroups: { "font-size": [{ text: ["caption"] }] } } });

/** Join class names and resolve Tailwind conflicts (the shadcn helper). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
