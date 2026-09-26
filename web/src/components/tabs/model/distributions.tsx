"use client";

import { NA } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Гистограмма длин prompt/generation-токенов (div-бары) из
 * distributions.{prompt,generation}_tokens — пары [le, count-дельта].
 */
function TokenHistogram({ title, buckets }: { title: string; buckets: [number, number][] }) {
  const rows = [...buckets].sort((a, b) => a[0] - b[0]).filter(([, c]) => c > 0);
  const max = Math.max(0, ...rows.map(([, c]) => c));
  const total = rows.reduce((s, [, c]) => s + c, 0);

  return (
    <div className="rounded-xl border border-line bg-panel p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-muted">всего: {total > 0 ? total : NA}</div>
      </div>
      {rows.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-sm text-muted">Нет данных</div>
      ) : (
        <div className="flex h-32 items-end gap-1">
          {rows.map(([le, count]) => (
            <div
              key={le}
              className="flex h-full flex-1 flex-col justify-end"
              title={`до ${le} токенов: ${count}`}
            >
              <div className="pb-0.5 text-center text-[10px] leading-none text-muted">
                {count}
              </div>
              <div
                className="w-full rounded-t bg-accent/80"
                style={{ height: `${max > 0 ? Math.max(2, (count / max) * 100) : 0}%` }}
              />
            </div>
          ))}
        </div>
      )}
      {rows.length > 0 && (
        <div className="mt-1 flex gap-1">
          {rows.map(([le]) => (
            <div key={le} className="flex-1 truncate text-center text-[10px] text-muted">
              ≤{le}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Две гистограммы периода: prompt и generation токены. */
export function TokenDistributions({
  distributions,
  className,
}: {
  distributions:
    | { prompt_tokens: [number, number][]; generation_tokens: [number, number][] }
    | null
    | undefined;
  className?: string;
}) {
  return (
    <div className={cn("grid grid-cols-1 gap-3 lg:grid-cols-2", className)}>
      <TokenHistogram
        title="Распределение prompt-токенов"
        buckets={distributions?.prompt_tokens ?? []}
      />
      <TokenHistogram
        title="Распределение generation-токенов"
        buckets={distributions?.generation_tokens ?? []}
      />
    </div>
  );
}
