import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-sm border px-2 py-0.5 text-sm font-medium", {
  variants: {
    variant: {
      default: "border-transparent bg-accent text-accent-fg",
      outline: "border-border text-fg",
      destructive: "border-transparent bg-danger text-danger-fg",
    },
  },
  defaultVariants: { variant: "outline" },
});

export type BadgeProps = ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
