import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

/** A shimmering placeholder bar. Decorative: hidden from assistive tech; the parent announces loading. */
export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div aria-hidden="true" className={cn("shimmer h-4 rounded-chip", className)} {...props} />;
}
