"use client";

import { HealthTab } from "@/components/tabs/health/health-tab";

/** Вкладка «Health» (F4.3): сводный статус сервиса/источников/GPU/системы. */
export default function HealthPage() {
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Health</h1>
      <HealthTab />
    </div>
  );
}
