"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { usePeriod, PERIOD_OPTIONS } from "@/lib/periods";
import { cn } from "@/lib/utils";

/** Чипы периодов + заглушка-поповер с двумя date-инпутами (контракт — usePeriod). */
export function PeriodSwitcher() {
  const { period, setPeriod, customFrom, customTo, setCustomRange } = usePeriod();
  const [customOpen, setCustomOpen] = useState(false);

  return (
    <div className="flex items-center gap-1">
      <div className="flex items-center gap-0.5 rounded-lg border border-line bg-panel p-0.5">
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => {
              setPeriod(opt.id);
              setCustomOpen(opt.id === "custom");
            }}
            className={cn(
              "rounded-md px-2 py-1 text-xs font-medium transition-colors",
              period === opt.id
                ? "bg-accent/15 text-accent"
                : "text-muted hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {period === "custom" && customOpen && (
        <div className="relative">
          <div className="absolute left-0 top-9 z-30 flex items-center gap-2 rounded-lg border border-line bg-panel p-2 shadow-lg">
            <input
              type="date"
              value={customFrom}
              onChange={(e) => setCustomRange(e.target.value, customTo)}
              className="h-7 rounded-md border border-line bg-panel2 px-2 text-xs text-foreground [color-scheme:dark]"
            />
            <span className="text-xs text-muted">—</span>
            <input
              type="date"
              value={customTo}
              onChange={(e) => setCustomRange(customFrom, e.target.value)}
              className="h-7 rounded-md border border-line bg-panel2 px-2 text-xs text-foreground [color-scheme:dark]"
            />
            <Button variant="ghost" size="sm" onClick={() => setCustomOpen(false)}>
              Готово
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
