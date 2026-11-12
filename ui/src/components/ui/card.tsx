import type { ComponentProps } from "react";
import type { SourceId } from "../../lib/sources";
import { cn } from "../../lib/utils";

/** A glass surface. With `source` it also glows in that source's color (scaled by the glow setting). */
export function Card({ className, source, ...props }: ComponentProps<"div"> & { source?: SourceId }) {
  return (
    <div
      className={cn("glass", source && "glow", className)}
      {...(source ? { "data-source": source } : {})}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1 p-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: ComponentProps<"h2">) {
  return <h2 className={cn("font-display text-lg font-semibold", className)} {...props} />;
}

export function CardContent({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("p-4 pt-0", className)} {...props} />;
}
