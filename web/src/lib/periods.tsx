"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Period } from "@/lib/types";

/**
 * Глобальный период выборки (ТЗ §5.1). Контракт готов к F1.2:
 * фиксированные периоды дают from/to в epoch-секундах, Live — null/null (SSE).
 */
export const PERIOD_OPTIONS: { id: Period; label: string; seconds: number | null }[] = [
  { id: "live", label: "Live", seconds: null },
  { id: "5m", label: "5м", seconds: 5 * 60 },
  { id: "1h", label: "1ч", seconds: 60 * 60 },
  { id: "24h", label: "24ч", seconds: 24 * 60 * 60 },
  { id: "7d", label: "7дн", seconds: 7 * 24 * 60 * 60 },
  { id: "30d", label: "30дн", seconds: 30 * 24 * 60 * 60 },
  { id: "custom", label: "произвольный", seconds: null },
];

interface PeriodState {
  period: Period;
  /** epoch-секунды; null для Live (и пока произвольный не задан) */
  from: number | null;
  to: number | null;
  /** произвольный диапазон — значения <input type="date"> (локальное время сервера) */
  customFrom: string;
  customTo: string;
  setPeriod: (p: Period) => void;
  setCustomRange: (from: string, to: string) => void;
}

const PeriodContext = createContext<PeriodState | null>(null);

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [period, setPeriodRaw] = useState<Period>("live");
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [customFrom, setCustomFrom] = useState(todayStr());
  const [customTo, setCustomTo] = useState(todayStr());

  const setPeriod = useCallback((p: Period) => {
    setPeriodRaw(p);
    if (p === "live") {
      setFrom(null);
      setTo(null);
      return;
    }
    const opt = PERIOD_OPTIONS.find((o) => o.id === p);
    const now = Math.floor(Date.now() / 1000);
    if (p === "custom") {
      // заглушка: from/to пересчитаются после выбора дат (F1.2)
      setFrom(null);
      setTo(null);
    } else if (opt?.seconds != null) {
      setFrom(now - opt.seconds);
      setTo(now);
    }
  }, []);

  const setCustomRange = useCallback((cf: string, ct: string) => {
    setCustomFrom(cf);
    setCustomTo(ct);
    setPeriodRaw("custom");
    const f = cf ? Math.floor(new Date(`${cf}T00:00:00`).getTime() / 1000) : null;
    const t = ct ? Math.floor(new Date(`${ct}T23:59:59`).getTime() / 1000) : null;
    setFrom(f);
    setTo(t);
  }, []);

  const value = useMemo<PeriodState>(
    () => ({ period, from, to, customFrom, customTo, setPeriod, setCustomRange }),
    [period, from, to, customFrom, customTo, setPeriod, setCustomRange],
  );

  return <PeriodContext.Provider value={value}>{children}</PeriodContext.Provider>;
}

export function usePeriod(): PeriodState {
  const ctx = useContext(PeriodContext);
  if (!ctx) throw new Error("usePeriod must be used within <PeriodProvider>");
  return ctx;
}
