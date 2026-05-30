"use client";

import { useState } from "react";
import type { InvoiceGenerateRequest, ContractGenerateRequest } from "@/types/api";
import { downloadExcel, downloadWord, triggerDownload } from "@/lib/api";

export function useDocumentExport() {
  const [loading, setLoading] = useState(false);

  const exportInvoice = async (
    productName: string,
    hsCode: string,
    invoicePrice: number,
  ) => {
    setLoading(true);
    try {
      const payload: InvoiceGenerateRequest = {
        seller_name: "FOREIGN VENDOR LTD (Шэньчжэнь, Китай)",
        buyer_name: "TOO KAZAKH IMPORTER (Алматы, Казахстан)",
        incoterms: "FCA Shenzhen",
        items: [
          {
            name: productName.trim() || "Таможенный товар (импорт)",
            hs_code: hsCode || "8517130000",
            qty: 1,
            unit: "pcs",
            price: Number(invoicePrice),
          },
        ],
      };
      const blob = await downloadExcel(payload);
      triggerDownload(blob, "Commercial_Invoice.xlsx");
    } catch (err) {
      console.error(err);
      alert("Ошибка при генерации инвойса");
    } finally {
      setLoading(false);
    }
  };

  const exportContract = async () => {
    setLoading(true);
    try {
      const payload: ContractGenerateRequest = {
        contract_no: "KED-2026/089",
        contract_date: new Date().toLocaleDateString("ru-RU", {
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
        seller_name: "FOREIGN VENDOR LTD (Китай)",
        buyer_name: "TOO KAZAKH IMPORTER (Казахстан)",
        incoterms: "DDP Almaty",
      };
      const blob = await downloadWord(payload);
      triggerDownload(blob, "Supply_Agreement.docx");
    } catch (err) {
      console.error(err);
      alert("Ошибка при генерации договора");
    } finally {
      setLoading(false);
    }
  };

  return { loading, exportInvoice, exportContract };
}
