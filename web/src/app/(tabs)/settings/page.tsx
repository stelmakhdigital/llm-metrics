"use client";

import { RatesForm, RatesHistory, useRates } from "@/components/tabs/cost/rates-form";
import { ErrorBanner } from "@/components/tabs/common";

/**
 * Вкладка «Настройки» (F2): карточка «Тарифы» — та же общая форма, что и во
 * вкладке «Стоимость» (GET/PUT /api/settings/cost через useRates).
 */
export default function SettingsPage() {
  const { history, error, loading } = useRates();
  return (
    <div className="max-w-3xl">
      <h1 className="mb-4 text-lg font-semibold">Настройки</h1>
      {error != null && <ErrorBanner message={error} />}
      <div className="rounded-xl border border-line bg-panel p-4">
        <div className="mb-3 text-sm font-medium">Тарифы</div>
        {loading && !error ? (
          <div className="h-24 animate-pulse rounded bg-panel2" />
        ) : (
          <RatesForm />
        )}
        {history.length > 0 && (
          <div className="mt-4 border-t border-line pt-2">
            <div className="mb-1 text-xs font-medium text-muted">
              Последние версии (изменение тарифа — новая версия)
            </div>
            <RatesHistory history={history} />
          </div>
        )}
      </div>
    </div>
  );
}
