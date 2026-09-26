import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const progressVariants = cva("relative w-full overflow-hidden rounded-full bg-panel2", {
  variants: {
    size: {
      sm: "h-1.5",
      default: "h-2",
    },
  },
  defaultVariants: { size: "default" },
});

export interface ProgressProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof progressVariants> {
  /** 0..100 */
  value: number;
  indicatorClassName?: string;
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, size, value, indicatorClassName, ...props }, ref) => {
    const clamped = Math.max(0, Math.min(100, value));
    return (
      <div ref={ref} role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}
        className={cn(progressVariants({ size }), className)} {...props}>
        <div
          className={cn("h-full rounded-full bg-accent transition-[width]", indicatorClassName)}
          style={{ width: `${clamped}%` }}
        />
      </div>
    );
  },
);
Progress.displayName = "Progress";

export { Progress, progressVariants };
