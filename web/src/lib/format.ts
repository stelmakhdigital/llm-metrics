/**
 * Общие форматтеры чисел для UI (ТЗ §5). null/undefined → «—» (нет данных).
 * Время в БД — epoch/UTC; отображение — локальное время сервера.
 */

export const NA = "—";

/** Число с фиксированным числом знаков (без тысячных разделителей). */
export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return NA;
  return v.toFixed(digits);
}

/** Целое число (KPI-счётчики: running, waiting, preemptions и т.п.). */
export function fmtInt(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  return String(Math.round(v));
}

/** Процент: 0.12 → «12%» (если значение уже в 0..100 — передавать как есть). */
export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${v.toFixed(digits)}%`;
}

/** Доля 0..1 → процент: 0.12 → «12%». */
export function fmtRatio(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${(v * 100).toFixed(digits)}%`;
}

/** Память из MiB → MiB/GiB. */
export function fmtMiB(vMib: number | null | undefined, digits = 1): string {
  if (vMib == null || Number.isNaN(vMib)) return NA;
  if (Math.abs(vMib) >= 1024) return `${(vMib / 1024).toFixed(digits)} GiB`;
  return `${vMib.toFixed(0)} MiB`;
}

/** Память из MB (10^6) → GB. */
export function fmtMb(vMb: number | null | undefined, digits = 1): string {
  if (vMb == null || Number.isNaN(vMb)) return NA;
  if (Math.abs(vMb) >= 1000) return `${(vMb / 1000).toFixed(digits)} GB`;
  return `${vMb.toFixed(0)} MB`;
}

/** Мощность: Вт / кВт. */
export function fmtW(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)} кВт`;
  return `${v.toFixed(0)} Вт`;
}

/** Частота МГц / ГГц. */
export function fmtMhz(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)} ГГц`;
  return `${v.toFixed(0)} МГц`;
}

/** Скорость сети Мбит/с. */
export function fmtMbps(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${v.toFixed(1)} Мбит/с`;
}

/** Диск MB/s. */
export function fmtMbS(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${v.toFixed(1)} МБ/с`;
}

/** Латентность: секунды → мс, если < 1 с. */
export function fmtLatency(vSec: number | null | undefined): string {
  if (vSec == null || Number.isNaN(vSec)) return NA;
  if (vSec < 1) return `${(vSec * 1000).toFixed(0)} мс`;
  return `${vSec.toFixed(2)} с`;
}

/** Токены/секунду. */
export function fmtTokS(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${v.toFixed(1)} tok/s`;
}

/** Запросы/секунду. */
export function fmtReqS(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${v.toFixed(2)}/с`;
}

/** epoch-с → «чч:мм» (локальное время сервера). */
export function fmtClock(ts: number | null | undefined): string {
  if (ts == null) return NA;
  return new Date(ts * 1000).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** epoch-с → «дд.мм чч:мм». */
export function fmtDateTime(ts: number | null | undefined): string {
  if (ts == null) return NA;
  const d = new Date(ts * 1000);
  return `${d.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  })} ${d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}

/** epoch-с → «чч:мм:сс» (для индикатора «обновлено»). */
export function fmtTimeS(ts: number | null | undefined): string {
  if (ts == null) return NA;
  return new Date(ts * 1000).toLocaleTimeString("ru-RU");
}

/** Частота обновления: «N с назад». */
export function fmtAgo(tsSec: number | null | undefined, nowSec?: number): string {
  if (tsSec == null) return NA;
  const now = nowSec ?? Date.now() / 1000;
  const d = Math.max(0, Math.round(now - tsSec));
  if (d < 60) return `${d} с назад`;
  if (d < 3600) return `${Math.round(d / 60)} мин назад`;
  return `${Math.round(d / 3600)} ч назад`;
}

/**
 * Форматтеры логов (ts — epoch-МИЛЛИсекунды, ТЗ §5.6: точность до мс).
 * Отображение — локальное время сервера.
 */

/** epoch-мс → «чч:мм:сс.ммм». */
export function fmtTimeMs(tsMs: number | null | undefined): string {
  if (tsMs == null || Number.isNaN(tsMs)) return NA;
  const d = new Date(tsMs);
  const p = (n: number, l = 2) => String(n).padStart(l, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

/** epoch-с → «дд.мм.гггг» (локальная полночь → дата дня). */
export function fmtDayFull(tsSec: number): string {
  return new Date(tsSec * 1000).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** epoch-с → «дд.мм» (короткая подпись дня на календарной шкале). */
export function fmtDayShort(tsSec: number): string {
  return new Date(tsSec * 1000).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  });
}

/** epoch-с → начало дня (локального) в epoch-с. */
export function startOfDaySec(tsSec: number): number {
  const d = new Date(tsSec * 1000);
  d.setHours(0, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
}

// ------------------------------------------------------------------ деньги

const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  RUB: "₽",
  CNY: "¥",
};

export function currencySymbol(code: string | null | undefined): string {
  return (code && CURRENCY_SYMBOLS[code.toUpperCase()]) || code || "$";
}

/** Деньги: 12.3456 → «$12.35»; малые значения (<0.01) — 4 знака. */
export function fmtMoney(v: number | null | undefined, currency?: string | null): string {
  if (v == null || Number.isNaN(v)) return NA;
  const sym = currencySymbol(currency);
  const digits = Math.abs(v) > 0 && Math.abs(v) < 0.01 ? 4 : 2;
  return `${sym}${v.toFixed(digits)}`;
}

/** Миллионы: 1_234_567 → «1,23M». */
export function fmtMillions(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return NA;
  return `${(v / 1_000_000).toFixed(digits)}M`;
}
