"use client";

import { usePeriod } from "@/lib/periods";
import { SystemLive } from "@/components/tabs/system/system-live";
import { SystemPeriod } from "@/components/tabs/system/system-period";

/**
 * Вкладка «Система» (ТЗ §5.4): Live — /api/system (poll 5 с, CPU/RAM/swap/
 * топ-5 процессов) + статус источника из SSE; период — /api/metrics/{metric}.
 */
export default function SystemPage() {
  const { period } = usePeriod();
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Система</h1>
      {period === "live" ? <SystemLive /> : <SystemPeriod />}
    </div>
  );
}
