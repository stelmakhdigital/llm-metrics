import type { Metadata } from "next";
import "./globals.css";
import { PeriodProvider } from "@/lib/periods";
import { ModelProvider } from "@/lib/model-context";
import { RefreshProvider } from "@/lib/refresh";

export const metadata: Metadata = {
  title: "llm-metrics",
  description:
    "Веб-мониторинг vLLM-сервера: модель, GPU, система, стоимость, логи",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <PeriodProvider>
          <ModelProvider>
            <RefreshProvider>{children}</RefreshProvider>
          </ModelProvider>
        </PeriodProvider>
      </body>
    </html>
  );
}
