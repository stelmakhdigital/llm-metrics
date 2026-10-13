import { cleanup, render, screen } from "@testing-library/react";
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
  // мобильные пункты нижней панели отличаются классом min-h-12 (десктопные — size-10)
  return screen.getAllByRole("link").filter((el) => el.className.includes("min-h-12"));
}

describe("Sidebar — мобильная нижняя панель (NavItemMobile)", () => {
  it("все 10 пунктов с русскими aria-label", () => {
    renderSidebar();
    const labels = [
      "Сводка", "Модель", "GPU", "Система", "Цена",
      "Логи", "Note", "Алерты", "Health", "Настр.",
    ];
    for (const label of labels) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it("активный пункт подсвечен (text-accent)", () => {
    renderSidebar();
    const active = mobileItems().find((el) => el.textContent === "Модель");
    expect(active?.className).toContain("text-accent");
    expect(active?.getAttribute("aria-label")).toBe("Модель");
  });

  it("каждый мобильный пункт — touch-target по высоте ≥ 40px (min-h-12 = 48px)", () => {
    renderSidebar();
    const items = mobileItems();
    expect(items.length).toBe(10);
    for (const item of items) {
      expect(item.className).toContain("min-h-12"); // 48px ≥ 40px
    }
  });
});
