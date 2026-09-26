"use client";

import { usePeriod } from "@/lib/periods";
import { ModelLive } from "@/components/tabs/model/model-live";
import { ModelPeriod } from "@/components/tabs/model/model-period";

/**
 * Вкладка «Модель» (ТЗ §5.2): Live — SSE (useLive) + KPI; период —
 * /api/model?from&to + графики /api/metrics/{metric}.
 */
export default function ModelPage() {
  const { period } = usePeriod();
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Модель (vLLM)</h1>
      {period === "live" ? <ModelLive /> : <ModelPeriod />}
    </div>
  );
}
