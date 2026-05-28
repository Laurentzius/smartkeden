import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Кеден Көмекшісі — ИИ-Помощник по Таможенному Оформлению",
  description: "Интеллектуальная система классификации ТН ВЭД, расчета пошлин и правового анализа RAG для Казахстана",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className="antialiased bg-slate-50 text-slate-900">
        {children}
      </body>
    </html>
  );
}
