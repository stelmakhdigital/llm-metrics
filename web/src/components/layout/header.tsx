"use client";

import { Activity, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PeriodSwitcher } from "@/components/layout/period-switcher";
import { fmtClock, useLive, useNow } from "@/lib/live";
import { cn } from "@/lib/utils";

const SOURCE_BADGES: { key: "vllm" | "gpu" | "system"; label: string }[] = [
  { key: "vllm", label: "vLLM" },
  { key: "gpu", label: "GPU" },
  { key: "system", label: "SYS" },
];

/**
 * Шапка: логотип + текущая модель + сводный статус |
 * бейджи статусов источников (vLLM/GPU/SYS) + переключатель периодов +
 * живой индикатор «● каждые 2 c  ЧЧ:ММ:СС» (lastUpdate из useLive, тикает раз в с).
 */
export function Header() {
  const { packet, connected, lastUpdate } = useLive();
  useNow(1000); // тик раз в секунду для часов

  const sources = packet?.sources ?? {};
  const anyOffline = Object.values(sources).includes("offline");

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-background/95 px-4 backdrop-blur">
      <div className="flex size-8 items-center justify-center rounded-lg bg-accent text-white">
        <Activity className="size-4" />
      </div>

      <Button variant="ghost" size="sm" className="gap-1.5 px-2 text-foreground">
        <span className="size-1.5 rounded-full bg-emerald-400" aria-hidden />
        {packet?.model ?? "Qwen3.8-27B"}
        <ChevronDown className="size-3.5 text-muted" />
      </Button>

      <Badge variant={anyOffline ? "destructive" : "success"}>
        {anyOffline ? "оффлайн" : "готов"}
      </Badge>

      <div className="ml-auto flex items-center gap-3">
        <div className="flex items-center gap-1">
          {SOURCE_BADGES.map(({ key, label }) => {
            const state = sources[key];
            return (
              <Badge key={key} variant="outline" className="gap-1.5 text-[11px]">
                <span
                  aria-hidden
                  className={cn(
                    "size-1.5 rounded-full",
                    state === "ok" && "bg-emerald-400",
                    state === "offline" && "bg-red-400",
                    state == null && "bg-muted/50",
                  )}
                />
                {label}
              </Badge>
            );
          })}
        </div>

        <PeriodSwitcher />

        <span className="flex items-center gap-1.5 text-xs text-muted">
          <span
            aria-hidden
            className={cn(
              "size-1.5 rounded-full",
              connected ? "bg-emerald-400" : "bg-red-400",
            )}
          />
          каждые 2 c
          <span className="tabular-nums text-foreground">{fmtClock(lastUpdate)}</span>
        </span>
      </div>
    </header>
  );
}
