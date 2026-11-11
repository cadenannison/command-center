import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

/** A grey placeholder block. Decorative: hidden from assistive tech; the parent announces loading. */
export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div aria-hidden="true" className={cn("h-4 animate-pulse rounded-md bg-border", className)} {...props} />;
}
