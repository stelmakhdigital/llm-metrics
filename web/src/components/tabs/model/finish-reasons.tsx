"use client";

import type { FinishReasons } from "@/lib/api";
import { cn } from "@/lib/utils";

const REASON_COLORS: Record<string, string> = {
  stop: "#34d399",
  length: "#facc15",
  abort: "#fb7185",
  error: "#f97316",
  repetition: "#a78bfa",
};

const REASON_LABELS: Record<string, string> = {
  stop: "stop",
  length: "length (макс. длина)",
  abort: "abort (отменён)",
  error: "error",
  repetition: "repetition",
};

/**
 * Причины финиша запросов (request_success_total_{reason}) — компактная
 * таблица с долями и цветной шкалой (вариант «doughnut-заменитель»).
 */
export function FinishReasons({
  reasons,
  className,
}: {
  reasons: FinishReasons | null | undefined;
  className?: string;
}) {
  const entries = Object.entries(reasons ?? {})
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);

  return (
    <div className={cn("rounded-xl border border-line bg-panel p-3", className)}>
      <div className="mb-2 text-sm font-medium">Причины финиша</div>
      {total === 0 ? (
        <div className="py-6 text-center text-sm text-muted">Нет данных</div>
      ) : (
        <div className="space-y-2">
          {entries.map(([reason, count]) => {
            const share = (count / total) * 100;
            const color = REASON_COLORS[reason] ?? "#38bdf8";
            return (
              <div key={reason}>
                <div className="mb-0.5 flex items-center justify-between text-xs">
                  <span className="text-muted">{REASON_LABELS[reason] ?? reason}</span>
                  <span>
                    {count} · {share.toFixed(1)}%
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${share}%`, backgroundColor: color }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
