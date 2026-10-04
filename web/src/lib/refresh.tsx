"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

/**
 * Глобальный «тут-сейчас»: кнопка «Обновить» в шапке инкрементирует tick,
 * и все usePoll/MetricChart пересчитывают запросы (обходя кэш fetchJson).
 */
interface RefreshState {
  tick: number;
  refresh: () => void;
}

const RefreshContext = createContext<RefreshState>({ tick: 0, refresh: () => {} });

export function RefreshProvider({ children }: { children: React.ReactNode }) {
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const value = useMemo(() => ({ tick, refresh }), [tick, refresh]);
  return <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>;
}

export function useRefresh(): RefreshState {
  return useContext(RefreshContext);
}
