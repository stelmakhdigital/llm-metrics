"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { fetchJson, MODELS_URL, type ModelInfo } from "@/lib/api";

/**
 * Глобальный селектор модели (F4.4, ТЗ §10.1).
 * model = null — «Все модели» (вся история); строка — фильтр вкладки
 * «Модель» (KPI и графики) по метке model (≤24ч — сырые, дальше — агрегаты).
 */
interface ModelState {
  /** выбранная модель или null (все) */
  model: string | null;
  setModel: (m: string | null) => void;
  /** исторический список моделей (свежие первыми) */
  models: ModelInfo[];
  loadingModels: boolean;
}

const ModelContext = createContext<ModelState | null>(null);

export function ModelProvider({ children }: { children: ReactNode }) {
  const [model, setModel] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchJson<{ models: ModelInfo[] }>(MODELS_URL)
      .then((d) => {
        if (!cancelled) setModels(d.models);
      })
      .catch(() => {
        /* оффлайн бэка — список пуст */
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <ModelContext.Provider
      value={{ model, setModel, models, loadingModels }}
    >
      {children}
    </ModelContext.Provider>
  );
}

export function useModel(): ModelState {
  const ctx = useContext(ModelContext);
  if (!ctx) throw new Error("useModel вне ModelProvider");
  return ctx;
}
