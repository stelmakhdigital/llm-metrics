"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LOGS_SOURCES_URL,
  logsExportUrl,
  logsUrl,
  usePoll,
  type LogRow,
  type LogSourcesData,
  type LogsPageData,
  type VllmLogStats,
} from "@/lib/api";
import { fmtTimeMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ErrorBanner, InfoBanner, NoData } from "../common";
import { LevelChip, LOG_LEVELS, LEVEL_CHIP_STYLES } from "./level";

/** Обрезка текста строки до клика. */
const LINE_TRUNCATE = 180;
const PAGE_SIZES = [100, 250, 500] as const;

/** Компактная боковая колонка stat-строк vLLM (running/waiting/KV%/throughput). */
function statsText(s: VllmLogStats | null): string {
  if (s == null) return "";
  const parts: string[] = [];
  if (s.running != null) parts.push(`R ${s.running}`);
  if (s.waiting != null) parts.push(`W ${s.waiting}`);
  if (s.kv_cache_pct != null) parts.push(`KV ${s.kv_cache_pct.toFixed(1)}%`);
  if (s.avg_prompt_throughput != null)
    parts.push(`P ${s.avg_prompt_throughput.toFixed(1)}/s`);
  if (s.avg_generation_throughput != null)
    parts.push(`G ${s.avg_generation_throughput.toFixed(1)}/s`);
  if (s.prefix_cache_hit_rate_pct != null)
    parts.push(`Pfx ${s.prefix_cache_hit_rate_pct.toFixed(1)}%`);
  return parts.join(" · ");
}

function RowLine({ line, expanded }: { line: string; expanded: boolean }) {
  if (expanded || line.length <= LINE_TRUNCATE) {
    return (
      <span className="whitespace-pre-wrap break-words">{line}</span>
    );
  }
  return (
    <span className="break-words text-muted">
      {line.slice(0, LINE_TRUNCATE)}…
    </span>
  );
}

function LogRowCell({
  row,
  expanded,
  onToggle,
  onCopy,
  copied,
}: {
  row: LogRow;
  expanded: boolean;
  onToggle: () => void;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <tr className="border-t border-line/40 align-top hover:bg-panel2/40">
      <td className="whitespace-nowrap py-1 pr-2 tabular-nums text-muted">
        {fmtTimeMs(row.ts)}
      </td>
      <td className="py-1 pr-2">
        <LevelChip level={row.level} />
      </td>
      <td className="whitespace-nowrap py-1 pr-2 text-muted">{row.source}</td>
      <td
        className="cursor-pointer py-1 pr-2 font-mono text-xs leading-5"
        onClick={onToggle}
        title={expanded ? "Свернуть" : "Показать полностью"}
      >
        <RowLine line={row.line} expanded={expanded} />
      </td>
      <td className="whitespace-nowrap py-1 pr-2 text-xs text-accent/90">
        {statsText(row.stats)}
      </td>
      <td className="py-1">
        <button
          type="button"
          onClick={onCopy}
          className="text-xs text-muted hover:text-foreground"
          title="Копировать строку"
        >
          {copied ? "✓" : "копировать"}
        </button>
      </td>
    </tr>
  );
}

/**
 * Режим «История» вкладки «Логи»: фильтры (уровень multi, текст, источник),
 * страницы 100/250/500, экспорт txt/csv, копирование строки,
 * автопарсинг stat-строк в боковую колонку.
 */
export function LogsHistory({ from, to }: { from: number; to: number }) {
  const [levels, setLevels] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [source, setSource] = useState("");
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZES)[number]>(100);
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  // дебаунс поиска по тексту (~300 мс)
  useEffect(() => {
    const t = setTimeout(() => setAppliedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const levelsKey = useMemo(() => [...levels].sort().join(","), [levels]);

  // сброс страницы при смене дня/фильтров
  useEffect(() => {
    setPage(0);
  }, [from, to, appliedQuery, source, levelsKey, pageSize]);

  const { data: sourcesData } = usePoll<LogSourcesData>(LOGS_SOURCES_URL, 60_000);
  const sources = sourcesData?.sources ?? [];

  const url = logsUrl({
    from,
    to,
    level: levelsKey || undefined,
    query: appliedQuery || undefined,
    source: source || undefined,
    offset: page * pageSize,
    limit: pageSize,
  });
  const { data, loading, error } = usePoll<LogsPageData>(url, 0);

  const toggleLevel = (lvl: string) => {
    setLevels((prev) => {
      const next = new Set(prev);
      if (next.has(lvl)) next.delete(lvl);
      else next.add(lvl);
      return next;
    });
  };

  const copyRow = useCallback(async (row: LogRow) => {
    const text = `${fmtTimeMs(row.ts)} ${row.level} [${row.source}] ${row.line}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(row.id);
      setTimeout(() => setCopiedId((c) => (c === row.id ? null : c)), 1500);
    } catch {
      /* clipboard недоступен (non-secure context) — молча пропускаем */
    }
  }, []);

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const exportParams = {
    from,
    to,
    level: levelsKey || undefined,
    query: appliedQuery || undefined,
    source: source || undefined,
  };

  return (
    <div className="space-y-3">
      {/* фильтры */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel p-3">
        <div className="flex items-center gap-1">
          {LOG_LEVELS.map((lvl) => {
            const active = levels.has(lvl);
            return (
              <button
                key={lvl}
                type="button"
                onClick={() => toggleLevel(lvl)}
                className={cn(
                  "rounded border px-2 py-0.5 text-[11px] font-semibold transition-colors",
                  active
                    ? LEVEL_CHIP_STYLES[lvl]
                    : "border-line bg-panel2 text-muted hover:text-foreground",
                )}
                title={active ? "Убрать уровень из фильтра" : "Добавить уровень в фильтр"}
              >
                {lvl}
              </button>
            );
          })}
          {levels.size > 0 && (
            <button
              type="button"
              onClick={() => setLevels(new Set())}
              className="ml-1 text-[11px] text-muted hover:text-foreground"
            >
              сбросить
            </button>
          )}
        </div>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск по тексту…"
          size="sm"
          className="w-56"
        />
        <Select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          title="Источник"
          className="text-xs"
        >
          <option value="">Все источники</option>
          {sources.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
              {s.status === "offline" ? " (offline)" : ""}
            </option>
          ))}
        </Select>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-xs text-muted">по</span>
          <Select
            value={String(pageSize)}
            onChange={(e) => setPageSize(Number(e.target.value) as (typeof PAGE_SIZES)[number])}
            className="text-xs"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
          <a
            className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs hover:border-accent/50 hover:text-accent"
            href={logsExportUrl({ ...exportParams, format: "txt" })}
            download
          >
            Скачать txt
          </a>
          <a
            className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs hover:border-accent/50 hover:text-accent"
            href={logsExportUrl({ ...exportParams, format: "csv" })}
            download
          >
            Скачать csv
          </a>
        </div>
      </div>

      {/* таблица */}
      {error != null && <ErrorBanner message={error} />}
      {loading && !data ? (
        <NoData text="Загрузка…" />
      ) : data && data.rows.length === 0 ? (
        <InfoBanner message="Нет строк лога по выбранным фильтрам за этот день." />
      ) : data ? (
        <div className="overflow-x-auto rounded-xl border border-line bg-panel">
          <table className="w-full min-w-[64rem] text-xs">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="px-3 py-2 font-medium">Время</th>
                <th className="px-2 py-2 font-medium">Уровень</th>
                <th className="px-2 py-2 font-medium">Источник</th>
                <th className="px-2 py-2 font-medium">Текст</th>
                <th className="px-2 py-2 font-medium">Stat vLLM</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <LogRowCell
                  key={row.id}
                  row={row}
                  expanded={expandedId === row.id}
                  onToggle={() => setExpandedId((e) => (e === row.id ? null : row.id))}
                  onCopy={() => void copyRow(row)}
                  copied={copiedId === row.id}
                />
              ))}
            </tbody>
          </table>
          {/* пагинация */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-xs text-muted">
            <span>
              всего: <span className="tabular-nums text-foreground">{total}</span>
              {total === 0 && data.rows.length === 0 ? " (пусто)" : ""}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="rounded-md border border-line bg-panel2 px-2 py-1 hover:border-accent/50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                ‹ пред.
              </button>
              <span className="tabular-nums">
                стр. {page + 1} из {pages}
              </span>
              <button
                type="button"
                disabled={!data.has_more}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border border-line bg-panel2 px-2 py-1 hover:border-accent/50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                след. ›
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
