import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "tnum inline-flex items-center rounded-chip px-2 py-0.5 font-display text-caption font-semibold",
  {
    variants: {
      variant: {
        default: "bg-chip text-fg",
        outline: "border border-line2 text-muted",
        accent: "bg-accent text-accent-fg",
        destructive: "bg-danger text-danger-fg",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export type BadgeProps = ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
