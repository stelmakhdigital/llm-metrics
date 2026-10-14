import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./sidebar";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/model"),
}));

afterEach(() => cleanup());

function renderSidebar() {
  return render(<Sidebar />);
}

function mobileItems() {
  // мобильные пункты — внутри нижней панели (устойчивый testid вместо
  // эвристики по классам, ломающейся при рефакторинге)
  return within(screen.getByTestId("mobile-nav")).getAllByRole("link");
}

describe("Sidebar — мобильная нижняя панель (NavItemMobile)", () => {
  it("все 10 пунктов доступны по русским aria-label", () => {
    renderSidebar();
    const labels = [
      "Сводка", "Модель", "GPU", "Система", "Цена",
      "Логи", "Note", "Алерты", "Health", "Настр.",
    ];
    for (const label of labels) {
      expect(screen.getAllByLabelText(label).length).toBeGreaterThan(0);
    }
  });

  it("активный пункт подсвечен (text-accent)", () => {
    renderSidebar();
    const active = mobileItems().find((el) => el.getAttribute("aria-label") === "Модель");
    expect(active?.className).toContain("text-accent");
  });

  it("компактный режим (>8 пунктов): иконки без подписей, без truncate", () => {
    renderSidebar();
    const items = mobileItems();
    expect(items.length).toBe(10);
    for (const item of items) {
      expect(item.className).not.toContain("truncate"); // деградации нет
      expect(item.textContent).toBe(""); // подписей нет, только иконка
      expect(item.getAttribute("aria-label")).toBeTruthy(); // имя сохранено
      expect(item.getAttribute("title")).toBeTruthy();
    }
  });

  it("touch-target ≥ 40px: min-w-10 (40px) × min-h-12 (48px) у каждого пункта", () => {
    renderSidebar();
    for (const item of mobileItems()) {
      expect(item.className).toContain("min-w-10"); // ширина ≥ 40px
      expect(item.className).toContain("min-h-12"); // высота ≥ 40px
      expect(item.className).toContain("shrink-0"); // не сжимается ниже минимума
    }
  });
});
