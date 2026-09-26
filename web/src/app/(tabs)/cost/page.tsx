"use client";

import { CostTab } from "@/components/tabs/cost/cost-tab";

/** Вкладка «Стоимость» (ТЗ §5.5). */
export default function CostPage() {
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Стоимость</h1>
      <CostTab />
    </div>
  );
}
