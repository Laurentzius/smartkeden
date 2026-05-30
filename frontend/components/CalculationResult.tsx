"use client";

import React from "react";
import { AlertTriangle, ShieldAlert, FileSpreadsheet, FileText, CheckCircle2 } from "lucide-react";
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
    <div className="space-y-4">
      {/* Error Block */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-800 rounded-xl text-xs flex items-start space-x-2.5 shadow-sm">
          <AlertTriangle className="h-4.5 w-4.5 text-red-500 shrink-0 mt-0.5" />
          <div>
            <span className="font-bold">Ошибка расчета:</span>{" "}
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Results Area */}
      {result && (
        <div className="space-y-5">
          <div className="flex items-center space-x-2 pb-1.5">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            <h3 className="font-bold text-slate-800 text-sm tracking-wide uppercase">
              Детализация платежей (Тенге)
            </h3>
          </div>

          <div className="space-y-3 text-sm bg-slate-50/50 p-4.5 rounded-2xl border border-slate-200/60">
            <div className="flex justify-between">
              <span className="text-slate-500">Таможенная стоимость (СВ):</span>
              <span className="font-bold text-slate-800 tabular-nums">
                {result.customs_value_kzt.toLocaleString()} ₸
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Таможенный сбор (фиксированный):</span>
              <span className="font-bold text-slate-800 tabular-nums">
                {result.customs_fee_kzt.toLocaleString()} ₸
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Импортная пошлина ({dutyRate}%):</span>
              <span className="font-bold text-slate-800 tabular-nums">
                {result.customs_duty_kzt.toLocaleString()} ₸
              </span>
            </div>
            {exciseRate > 0 && (
              <div className="flex justify-between">
                <span className="text-slate-500">Акциз ({exciseRate}%):</span>
                <span className="font-bold text-slate-800 tabular-nums">
                  {result.excise_kzt.toLocaleString()} ₸
                </span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-slate-500">Импортный НДС (12%):</span>
              <span className="font-bold text-slate-800 tabular-nums">
                {result.import_vat_kzt.toLocaleString()} ₸
              </span>
            </div>
            {result.recycling_fee_kzt > 0 && (
              <div className="flex justify-between">
                <span className="text-slate-500">Утилизационный сбор:</span>
                <span className="font-bold text-slate-800 tabular-nums">
                  {result.recycling_fee_kzt.toLocaleString()} ₸
                </span>
              </div>
            )}

            <div className="flex justify-between border-t border-slate-200/80 pt-3.5 mt-3 text-base font-extrabold text-slate-900">
              <span>Итого к уплате:</span>
              <span className="text-blue-600 text-xl font-black tabular-nums">
                {result.total_payments_kzt.toLocaleString()} ₸
              </span>
            </div>
          </div>
          {/* TROIS Warning */}
          {result.trois_warning && (
            <div className="p-3.5 bg-amber-50 border border-amber-200 text-amber-900 rounded-xl text-xs flex items-start space-x-2.5">
              <ShieldAlert className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold block text-amber-850 mb-0.5">Внимание ТРОИС:</span>
                <span className="leading-relaxed">{result.trois_warning}</span>
              </div>
            </div>
          )}

          {/* Document Export */}
          <div className="pt-4 border-t border-slate-100 flex flex-col space-y-2.5">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              Экспорт документов
            </span>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={onExportInvoice}
                disabled={docLoading}
                className="flex items-center justify-center space-x-2 border border-slate-200 hover:border-blue-500 hover:text-blue-600 hover:bg-blue-50/10 text-slate-700 bg-white px-3.5 py-3 rounded-xl text-xs font-bold transition-all duration-150 cursor-pointer disabled:opacity-50 shadow-xs focus:outline-hidden focus:ring-2 focus:ring-blue-500/30 min-h-11"
                aria-label="Экспортировать инвойс в формате Excel"
              >
                <FileSpreadsheet className="h-4 w-4 text-emerald-600 shrink-0" />
                <span>Инвойс (Excel)</span>
              </button>
              <button
                type="button"
                onClick={onExportContract}
                disabled={docLoading}
                className="flex items-center justify-center space-x-2 border border-slate-200 hover:border-blue-500 hover:text-blue-600 hover:bg-blue-50/10 text-slate-700 bg-white px-3.5 py-3 rounded-xl text-xs font-bold transition-all duration-150 cursor-pointer disabled:opacity-50 shadow-xs focus:outline-hidden focus:ring-2 focus:ring-blue-500/30 min-h-11"
                aria-label="Экспортировать договор в формате Word"
              >
                <FileText className="h-4 w-4 text-blue-600 shrink-0" />
                <span>Договор (Word)</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
