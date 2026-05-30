"use client";

import React from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import type { CalculationResponse } from "@/types/api";

interface CalculationResultProps {
  result: CalculationResponse | null;
  error: string | null;
  dutyRate: number;
  exciseRate: number;
  docLoading: boolean;
  onExportInvoice: () => void;
  onExportContract: () => void;
}

export function CalculationResult({
  result,
  error,
  dutyRate,
  exciseRate,
  docLoading,
  onExportInvoice,
  onExportContract,
}: CalculationResultProps) {
  return (
    <>
      {/* Error Block */}
      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs flex items-center space-x-2">
          <AlertTriangle className="h-4 w-4 text-red-500 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Area */}
      {result && (
        <div className="mt-6 border-t border-slate-200 pt-6 space-y-4">
          <h3 className="font-bold text-slate-800 text-sm tracking-wide uppercase">
            Детализация платежей (Тенге)
          </h3>

          <div className="space-y-2 text-sm bg-slate-50 p-4 rounded-xl border border-slate-100">
            <div className="flex justify-between">
              <span className="text-slate-500">Таможенная стоимость (СВ):</span>
              <span className="font-semibold text-slate-800">
                {result.customs_value_kzt.toLocaleString()} ₸
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Таможенный сбор (фиксированный):</span>
              <span className="font-semibold text-slate-800">
                {result.customs_fee_kzt.toLocaleString()} ₸
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Импортная пошлина ({dutyRate}%):</span>
              <span className="font-semibold text-slate-800">
                {result.customs_duty_kzt.toLocaleString()} ₸
              </span>
            </div>
            {exciseRate > 0 && (
              <div className="flex justify-between">
                <span className="text-slate-500">Акциз ({exciseRate}%):</span>
                <span className="font-semibold text-slate-800">
                  {result.excise_kzt.toLocaleString()} ₸
                </span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-slate-500">Импортный НДС (12%):</span>
              <span className="font-semibold text-slate-800">
                {result.import_vat_kzt.toLocaleString()} ₸
              </span>
            </div>
            {result.recycling_fee_kzt > 0 && (
              <div className="flex justify-between">
                <span className="text-slate-500">Утилизационный сбор:</span>
                <span className="font-semibold text-slate-800">
                  {result.recycling_fee_kzt.toLocaleString()} ₸
                </span>
              </div>
            )}

            <div className="flex justify-between border-t border-slate-200 pt-3 mt-2 text-base font-bold text-slate-950">
              <span>Итого к уплате:</span>
              <span className="text-teal-600">
                {result.total_payments_kzt.toLocaleString()} ₸
              </span>
            </div>
          </div>

          {/* TROIS Warning */}
          {result.trois_warning && (
            <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg text-xs flex items-start space-x-2">
              <ShieldAlert className="h-5 w-5 text-amber-600 shrink-0" />
              <div>
                <span className="font-bold">Внимание ТРОИС:</span>{" "}
                {result.trois_warning}
              </div>
            </div>
          )}

          {/* Document Export */}
          <div className="pt-4 border-t border-slate-100 flex flex-col space-y-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Экспорт документов
            </span>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={onExportInvoice}
                disabled={docLoading}
                className="flex items-center justify-center space-x-1.5 border border-slate-300 hover:border-teal-500 hover:text-teal-600 text-slate-700 bg-white px-3 py-2 rounded-lg text-xs font-bold transition duration-150 cursor-pointer disabled:opacity-50"
              >
                <span>📊 Скачать Инвойс (Excel)</span>
              </button>
              <button
                type="button"
                onClick={onExportContract}
                disabled={docLoading}
                className="flex items-center justify-center space-x-1.5 border border-slate-300 hover:border-teal-500 hover:text-teal-600 text-slate-700 bg-white px-3 py-2 rounded-lg text-xs font-bold transition duration-150 cursor-pointer disabled:opacity-50"
              >
                <span>📝 Скачать Договор (Word)</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
