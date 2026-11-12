import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

// Click targets: 32px by default, 28px for small buttons (spec, Tokens).
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-control font-medium transition-colors duration-140 ease-cc disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-fg hover:opacity-90",
        outline: "border border-line2 bg-chip text-fg hover:bg-line",
        ghost: "text-fg hover:bg-chip",
        destructive: "bg-danger text-danger-fg hover:opacity-90",
      },
      size: {
        default: "min-h-8 px-4",
        sm: "min-h-7 px-3 text-caption",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
