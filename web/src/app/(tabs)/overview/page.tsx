"use client";

import { OverviewTab } from "@/components/tabs/overview/overview-tab";

/** Вкладка «Сводка» — главная страница: статус стека, KPI, GPU, стоимость, алерты. */
export default function OverviewPage() {
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Сводка</h1>
      <OverviewTab />
    </div>
  );
}
