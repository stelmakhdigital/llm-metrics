import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const inputVariants = cva(
  "flex h-8 w-full rounded-md border border-line bg-panel2 px-3 text-sm text-foreground placeholder:text-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent disabled:opacity-50",
  {
    variants: { size: { sm: "h-7 text-xs", default: "h-8" } },
    defaultVariants: { size: "default" },
  },
);

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">,
    VariantProps<typeof inputVariants> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, size, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(inputVariants({ size }), "[color-scheme:dark]", className)}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input, inputVariants };
