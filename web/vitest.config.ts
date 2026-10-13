import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
  // tsconfig имеет jsx: "preserve" (для next) — в тестах нужен automatic runtime
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  // tailwind v4 (@tailwindcss/postcss) не нужен в тестах — CSS не импортируется;
  // inline css.postcss отключает поиск postcss.config.mjs (vite 5.4 не умеет его грузить)
  css: { postcss: { plugins: [] } },
  resolve: {
    alias: {
      "@": path.resolve(process.cwd(), "src"),
    },
  },
});
