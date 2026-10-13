import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PERIOD_OPTIONS, PeriodProvider, todayStr, usePeriod } from "./periods";

// TZ≠UTC — проверка фикса df38a5d (todayStr/local-даты в setCustomRange)
beforeEach(() => {
  process.env.TZ = "America/New_York";
});
afterEach(() => {
  process.env.TZ = "";
  vi.useRealTimers();
});

describe("todayStr — локальная дата (фикс df38a5d)", () => {
  it("возвращает локальную дату, когда UTC уже другой день", () => {
    // 2023-12-31T20:30 EST = 2024-01-01T01:30Z: UTC-дата «2024-01-01», локальная «2023-12-31»
    vi.useFakeTimers();
    vi.setSystemTime(1704072600000);
    expect(todayStr()).toBe("2023-12-31");
  });

  it("летнее время (EDT) — тоже локальная дата", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1717223400000); // 2024-06-01T02:30 EDT = 06:30Z
    expect(todayStr()).toBe("2024-06-01");
  });
});

describe("PERIOD_OPTIONS", () => {
  it("Live и произвольный без seconds, фиксы — с длительностью", () => {
    expect(PERIOD_OPTIONS.find((o) => o.id === "live")?.seconds).toBeNull();
    expect(PERIOD_OPTIONS.find((o) => o.id === "custom")?.seconds).toBeNull();
    expect(PERIOD_OPTIONS.find((o) => o.id === "24h")?.seconds).toBe(86400);
  });
});

describe("usePeriod", () => {
  function hook() {
    return renderHook(() => usePeriod(), { wrapper: PeriodProvider });
  }

  it("бросает ошибку вне провайдера", () => {
    expect(() => renderHook(() => usePeriod())).toThrow(
      "usePeriod must be used within <PeriodProvider>",
    );
  });

  it("live — from/to null (SSE)", () => {
    const { result } = hook();
    expect(result.current.period).toBe("live");
    expect(result.current.from).toBeNull();
    expect(result.current.to).toBeNull();
  });

  it("фиксированный период даёт окно в epoch-секундах", () => {
    const { result } = hook();
    act(() => result.current.setPeriod("24h"));
    const now = Math.floor(Date.now() / 1000);
    expect(result.current.period).toBe("24h");
    expect(now - result.current.from!).toBe(86400);
    expect(Math.abs(now - result.current.to!)).toBeLessThanOrEqual(2);
  });

  it("custom — заглушка null/null до выбора дат", () => {
    const { result } = hook();
    act(() => result.current.setPeriod("custom"));
    expect(result.current.from).toBeNull();
    expect(result.current.to).toBeNull();
  });

  it("setCustomRange — локальная полночь в epoch (фикс df38a5d)", () => {
    const { result } = hook();
    act(() => result.current.setCustomRange("2024-06-01", "2024-06-01"));
    expect(result.current.period).toBe("custom");
    expect(result.current.customFrom).toBe("2024-06-01");
    // EDT: 2024-06-01T00:00:00-04:00 → 1717214400; 23:59:59 → 1717300799
    expect(result.current.from).toBe(1717214400);
    expect(result.current.to).toBe(1717300799);
  });

  it("пустые даты в setCustomRange — from/to null", () => {
    const { result } = hook();
    act(() => result.current.setCustomRange("", ""));
    expect(result.current.from).toBeNull();
    expect(result.current.to).toBeNull();
  });
});
