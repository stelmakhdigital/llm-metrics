"use client";

import { useEffect, useState } from "react";

/** Снимок одного GPU (контракт: docs/api-contracts.md, GET /api/live). */
export type GpuSnapshot = {
  id: number;
  name: string;
  power_w: number | null;
  power_limit_w: number | null;
  mem_used_mib: number | null;
  mem_total_mib: number | null;
  util: number | null;
  temp: number | null;
  sm_clock_mhz: number | null;
  mem_clock_mhz: number | null;
  throttle: string[];
  ecc_correctable: number;
  ecc_uncorrectable: number;
};

/** Пакет SSE /api/live. Блоки offline-источников приходят null. */
export type LivePacket = {
  ts: number;
  sources: Record<string, "ok" | "offline">;
  model: string | null;
  kpi: Record<string, number | null> | null;
  gpu_total: { power_w: number; mem_used_mib: number; mem_total_mib: number } | null;
  gpus: GpuSnapshot[] | null;
  system: Record<string, number> | null;
  /** F4.1: число активных алертов (колокольчик в шапке) */
  alerts_active: number;
};

/** Точка суммарной мощности (ring buffer ~5 минут). */
export type LivePowerPoint = { ts: number; power_w: number };

export type LiveState = {
  /** последний пакет */
  packet: LivePacket | null;
  /** SSE жив */
  connected: boolean;
  /** ts последнего пакета (epoch-с) */
  lastUpdate: number | null;
  /** ring ~5 минут из gpu_total.power_w */
  powerHistory: LivePowerPoint[];
};

const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 15000];
const HISTORY_WINDOW_S = 5 * 60;

/**
 * Общий хук SSE /api/live (НОРМАТИВНАЯ сигнатура, docs/api-contracts.md).
 * Автопереподключение с exponential backoff до 15 с; powerHistory — ring ~5 мин.
 */
export function useLive(): LiveState {
  const [packet, setPacket] = useState<LivePacket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [powerHistory, setPowerHistory] = useState<LivePowerPoint[]>([]);

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let attempts = 0;

    const connect = () => {
      if (stopped) return;
      es = new EventSource("/api/live");
      es.onopen = () => {
        attempts = 0;
        setConnected(true);
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        es = null;
        const delay = RECONNECT_DELAYS_MS[Math.min(attempts, RECONNECT_DELAYS_MS.length - 1)];
        attempts += 1;
        timer = setTimeout(connect, delay);
      };
      es.onmessage = (event: MessageEvent<string>) => {
        let p: LivePacket;
        try {
          p = JSON.parse(event.data) as LivePacket;
        } catch {
          return; // повреждённый пакет — игнорируем, ждём следующий
        }
        setPacket(p);
        if (typeof p.ts === "number") setLastUpdate(p.ts);
        const total = p.gpu_total;
        if (total && typeof total.power_w === "number" && typeof p.ts === "number") {
          setPowerHistory((prev) => {
            const cutoff = p.ts - HISTORY_WINDOW_S;
            const next = prev.filter((pt) => pt.ts > cutoff);
            next.push({ ts: p.ts, power_w: total.power_w });
            return next;
          });
        }
      };
    };

    connect();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, []);

  return { packet, connected, lastUpdate, powerHistory };
}

/** Тикает раз в `intervalMs` мс (для «ЧЧ:ММ:СС» в шапке/блоках Live). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** epoch-с → «ЧЧ:ММ:СС» (локальное время сервера); null → «—:—:—». */
export function fmtClock(ts: number | null): string {
  if (ts == null) return "—:—:—";
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
