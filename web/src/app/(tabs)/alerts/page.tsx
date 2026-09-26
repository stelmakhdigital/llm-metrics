"use client";

import { AlertsTab } from "@/components/tabs/alerts/alerts-tab";

/** Вкладка «Алерты» (F4.1): активные алерты, настройки, журнал. */
export default function AlertsPage() {
  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">Алерты</h1>
      <AlertsTab />
    </div>
  );
}
