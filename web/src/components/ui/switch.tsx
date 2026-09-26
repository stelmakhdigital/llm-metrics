"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const switchVariants = cva("relative inline-flex shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent", {
  variants: {
    size: {
      default: "h-5 w-9",
      sm: "h-4 w-7",
    },
  },
  defaultVariants: { size: "default" },
});

export interface SwitchProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange">,
    VariantProps<typeof switchVariants> {
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ className, size, checked, onCheckedChange, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      className={cn(switchVariants({ size }), checked ? "bg-accent" : "bg-panel2 border border-line", className)}
      onClick={() => onCheckedChange?.(!checked)}
      {...props}
    >
      <span
        className={cn(
          "block rounded-full bg-white transition-transform",
          size === "sm" ? "size-3" : "size-4",
          checked
            ? size === "sm"
              ? "translate-x-3.5"
              : "translate-x-4.5"
            : size === "sm"
              ? "translate-x-0.5"
              : "translate-x-0.5",
        )}
      />
    </button>
  ),
);
Switch.displayName = "Switch";

export { Switch, switchVariants };
