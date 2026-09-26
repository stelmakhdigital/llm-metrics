"use client";

import { Badge } from "@/components/ui/badge";
import type { ModelSegment } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

/**
 * Шапка вкладки «Модель»: бейджи моделей, обслуживавших выбранный период.
 * При 2+ моделях — с подписями сегментов (диапазон действия каждой).
 */
export function ModelBadges({ models }: { models: ModelSegment[] | null | undefined }) {
  const list = models ?? [];
  if (list.length === 0) return null;
  const multi = list.length > 1;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted">Модель(и) периода:</span>
      {list.map((m, i) => (
        <Badge key={`${m.name}-${m.from}`} variant={i === 0 ? "accent" : "default"}>
          {m.name}
          {multi && (
            <span className="font-normal text-muted">
              {fmtDateTime(m.from)} – {fmtDateTime(m.to)}
            </span>
          )}
        </Badge>
      ))}
      {multi && (
        <span className="text-xs text-muted">
          на графиках границы смены модели отмечены оранжевыми пунктирными линиями
        </span>
      )}
    </div>
  );
}
