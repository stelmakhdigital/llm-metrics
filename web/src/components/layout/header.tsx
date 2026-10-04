"use client";

import { useState } from "react";
import Link from "next/link";
import { Activity, Bell, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { PeriodSwitcher } from "@/components/layout/period-switcher";
import { fmtClock, useLive, useNow } from "@/lib/live";
import { useModel } from "@/lib/model-context";
import { useRefresh } from "@/lib/refresh";
import { bustCache } from "@/lib/api";
import { cn } from "@/lib/utils";

const SOURCE_BADGES: { key: "vllm" | "gpu" | "system"; label: string }[] = [
  { key: "vllm", label: "vLLM" },
  { key: "gpu", label: "GPU" },
  { key: "system", label: "SYS" },
];

/**
 * Шапка: логотип + селектор модели (F4.4) + сводный статус |
 * бейджи статусов источников (vLLM/GPU/SYS) + колокольчик алертов (F4.1) +
 * переключатель периодов + живой индикатор «● каждые 2 c  ЧЧ:ММ:СС».
 */
export function Header() {
  const { packet, connected, lastUpdate } = useLive();
  useNow(1000); // тик раз в секунду для часов
  const { model, setModel, models } = useModel();
  const { refresh } = useRefresh();
  const [spinning, setSpinning] = useState(false);
  const onRefresh = () => {
    bustCache();
    refresh();
    setSpinning(true);
    window.setTimeout(() => setSpinning(false), 600);
  };

  const sources = packet?.sources ?? {};
  const anyOffline = Object.values(sources).includes("offline");
  const alertsActive = packet?.alerts_active ?? 0;

  // текущая модель vLLM (из live-пакета) — если её ещё нет в истории, добавить
  const liveModel = packet?.model;
  const modelOptions =
    liveModel && !models.some((m) => m.name === liveModel)
      ? [{ name: liveModel, from: 0, to: 0, count: 0 }, ...models]
      : models;

  return (
    <header className="sticky top-0 z-30 flex flex-col border-b border-line bg-background/95 px-3 backdrop-blur md:flex-row md:items-center md:px-4">
      {/* Строка 1: логотип, модель, статус + (алерт, обновить) */}
      <div className="flex min-h-14 items-center gap-2 py-2 md:min-h-0 md:flex-1 md:gap-3 md:py-0">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
          <Activity className="size-4" />
        </div>

        <Select
          value={model ?? ""}
          onChange={(e) => setModel(e.target.value || null)}
          aria-label="Модель"
          className="min-w-0 flex-1 md:w-56 md:flex-none"
        >
          <option value="">Все модели</option>
          {modelOptions.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </Select>

        <Badge variant={anyOffline ? "destructive" : "success"} className="shrink-0">
          {anyOffline ? "оффлайн" : "готов"}
        </Badge>

        <div className="ml-auto flex shrink-0 items-center gap-1.5 md:gap-3">
          <div className="hidden items-center gap-1 md:flex">
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

          <Link
            href="/alerts"
            title="Алерты"
            className="relative rounded-lg p-2 text-muted transition-colors hover:bg-panel2 hover:text-foreground"
          >
            <Bell className="size-4" />
            {alertsActive > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
                {alertsActive}
              </span>
            )}
          </Link>

          <button
            type="button"
            onClick={onRefresh}
            title="Обновить данные"
            className="rounded-lg p-2 text-muted transition-colors hover:bg-panel2 hover:text-foreground"
          >
            <RefreshCw className={cn("size-4", spinning && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Строка 2 (на <md — отдельная, на md+ инлайн): периоды + часы */}
      <div className="-my-0.5 flex items-center gap-3 overflow-x-auto py-2 md:py-0">
        <div className="shrink-0">
          <PeriodSwitcher />
        </div>
        <span className="hidden shrink-0 items-center gap-1.5 text-xs text-muted md:flex">
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
