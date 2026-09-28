"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { putJson, usePoll } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { CostRateUpdate, CostRateVersion, CostRatesSettings } from "@/lib/types";

// ------------------------------------------------------------------ useRates

/**
 * Единый хук тарифов (GET/PUT /api/settings/cost): используют вкладка
 * «Стоимость» и карточка в «Настройках».
 */
export function useRates() {
  const { data, loading, error, refresh } = usePoll<CostRatesSettings>(
    "/api/settings/cost",
    0,
  );
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const save = useCallback(
    async (upd: CostRateUpdate) => {
      setSaving(true);
      setNotice(null);
      try {
        await putJson<CostRatesSettings>("/api/settings/cost", upd);
        refresh(); // новая версия тарифа
        setNotice("Тариф сохранён — история пересчитывается автоматически");
      } catch (e: unknown) {
        setNotice(e instanceof Error ? e.message : "Ошибка сохранения");
      } finally {
        setSaving(false);
      }
    },
    [refresh],
  );

  return {
    current: data?.current ?? null,
    history: data?.history ?? [],
    loading,
    error,
    saving,
    notice,
    save,
  };
}

// ------------------------------------------------------------------ RatesForm

type Field = keyof Omit<CostRateVersion, "updated_at">;

const FIELDS: { key: Exclude<Field, "currency">; label: string; step?: string; min?: string }[] = [
  { key: "token_prompt_per_million_usd", label: "$ / 1M prompt-токенов", step: "0.01", min: "0" },
  { key: "token_completion_per_million_usd", label: "$ / 1M completion-токенов", step: "0.01", min: "0" },
  { key: "rate_per_kwh_usd", label: "$ / кВт·ч", step: "0.01", min: "0" },
  { key: "system_baseline_watts", label: "Системный baseline, Вт", step: "1", min: "0" },
];

/**
 * Форма тарифов (общая: вкладка «Стоимость» + «Настройки»).
 * Ключ `rate.updated_at` — пересоздание формы при смене текущей версии.
 */
export function RatesForm() {
  const { current, error, saving, notice, save } = useRates();
  const [values, setValues] = useState<Record<Field, string>>({
    currency: "USD",
    token_prompt_per_million_usd: "0.5",
    token_completion_per_million_usd: "1.5",
    rate_per_kwh_usd: "0.1",
    system_baseline_watts: "200",
  });

  // Заполнить поля текущей версией при первой загрузке и при смене версии.
  useEffect(() => {
    if (!current) return;
    setValues({
      currency: current.currency,
      token_prompt_per_million_usd: String(current.token_prompt_per_million_usd),
      token_completion_per_million_usd: String(current.token_completion_per_million_usd),
      rate_per_kwh_usd: String(current.rate_per_kwh_usd),
      system_baseline_watts: String(current.system_baseline_watts),
    });
  }, [current?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: Field, v: string) => setValues((s) => ({ ...s, [k]: v }));

  // Пустое/некорректное поле — форма невалидна (Number("") = 0 не уходит тихо).
  const parsed = FIELDS.map((f) => {
    const raw = values[f.key].trim();
    if (raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  });
  const valid = parsed.every((n) => n !== null);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    const upd: CostRateUpdate = { currency: values.currency.trim().toUpperCase() };
    for (let i = 0; i < FIELDS.length; i++) {
      if (parsed[i] !== null) upd[FIELDS[i].key] = parsed[i];
    }
    void save(upd);
  };

  if (error != null) {
    return <div className="text-sm text-red-400">Ошибка API: {error}</div>;
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {FIELDS.map((f) => (
          <label key={f.key} className="block">
            <span className="mb-1 block text-xs text-muted">{f.label}</span>
            <Input
              type="number"
              step={f.step}
              min={f.min}
              value={values[f.key]}
              onChange={(e) => set(f.key, e.target.value)}
            />
          </label>
        ))}
        <label className="block">
          <span className="mb-1 block text-xs text-muted">Валюта (код)</span>
          <Input
            type="text"
            value={values.currency}
            onChange={(e) => set("currency", e.target.value)}
          />
        </label>
        <div className="flex items-end">
          <Button type="submit" disabled={saving || !valid}>
            {saving ? "Сохранение…" : "Сохранить"}
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted">
        История пересчитывается автоматически: тариф версионируется, для каждого
        часа применяются значения, действовавшие в тот момент.
      </p>
      {notice != null && <p className="text-xs text-accent">{notice}</p>}
    </form>
  );
}

// --------------------------------------------------------------- RatesHistory

/** Компактный список последних версий тарифа (новые первыми). */
export function RatesHistory({ history }: { history: CostRateVersion[] }) {
  if (history.length === 0) return null;
  return (
    <ul className="divide-y divide-line text-xs text-muted">
      {history.slice(0, 5).map((v, i) => (
        <li key={`${v.updated_at}-${i}`} className="py-1.5">
          <span className="text-foreground/70">{fmtDateTime(v.updated_at)}</span>
          {" · in $"}
          {v.token_prompt_per_million_usd}
          {" / out $"}
          {v.token_completion_per_million_usd}
          {" / $"}
          {v.rate_per_kwh_usd}
          {" кВт·ч / baseline "}
          {v.system_baseline_watts}W
          {v.currency ? ` (${v.currency})` : ""}
        </li>
      ))}
    </ul>
  );
}
