"use client";

import React from "react";
import { Calculator } from "lucide-react";

interface CalculatorFormProps {
  invoicePrice: number;
  onInvoicePriceChange: (v: number) => void;
  currency: string;
  onCurrencyChange: (v: string) => void;
  customRate: number;
  onCustomRateChange: (v: number) => void;
  transportCost: number;
  onTransportCostChange: (v: number) => void;
  dutyRate: number;
  onDutyRateChange: (v: number) => void;
  exciseRate: number;
  onExciseRateChange: (v: number) => void;
  isRecycling: boolean;
  onRecyclingChange: (v: boolean) => void;
  loading: boolean;
  onSubmit: (e: React.FormEvent) => void;
}

export function CalculatorForm({
  invoicePrice,
  onInvoicePriceChange,
  currency,
  onCurrencyChange,
  customRate,
  onCustomRateChange,
  transportCost,
  onTransportCostChange,
  dutyRate,
  onDutyRateChange,
  exciseRate,
  onExciseRateChange,
  isRecycling,
  onRecyclingChange,
  loading,
  onSubmit,
}: CalculatorFormProps) {
  return (
    <section className="bg-white border border-slate-200/80 rounded-2xl shadow-sm p-6 flex flex-col h-fit transition-all duration-200 hover:shadow-md hover:border-slate-200">
      <div className="flex items-center space-x-2.5 border-b border-slate-100 pb-4 mb-6">
        <div className="bg-teal-50 p-2 rounded-lg text-teal-600">
          <Calculator className="h-5 w-5" />
        </div>
        <h2 className="font-bold text-base text-slate-800">Калькулятор таможенных платежей</h2>
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1">
            Фактурная стоимость товара
          </label>
          <div className="relative rounded-md shadow-sm flex">
            <input
              type="number"
              required
              min="0.01"
              step="any"
              value={invoicePrice}
              onChange={(e) => onInvoicePriceChange(parseFloat(e.target.value) || 0)}
              className="block w-full rounded-l-lg border border-slate-300 px-3.5 py-2.5 text-slate-900 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/10 focus:outline-none text-sm transition-all"
              placeholder="Например, 1500"
            />
            <select
              value={currency}
              onChange={(e) => onCurrencyChange(e.target.value)}
              className="rounded-r-lg border border-l-0 border-slate-300 bg-slate-50 px-3.5 py-2.5 text-slate-700 text-sm focus:border-teal-500 focus:outline-none cursor-pointer hover:bg-slate-100 transition-colors"
            >
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="CNY">CNY</option>
              <option value="RUB">RUB</option>
              <option value="KZT">KZT</option>
            </select>
          </div>
        </div>

        {/* Custom/Resolved exchange rate */}
        {currency !== "KZT" && (
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">
              Курс валюты к тенге (KZT)
            </label>
            <input
              type="number"
              required
              min="0.01"
              step="any"
              value={customRate}
              onChange={(e) => onCustomRateChange(parseFloat(e.target.value) || 1)}
              className="block w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-slate-900 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/10 focus:outline-none text-sm transition-all"
            />
          </div>
        )}

        {/* Transport costs */}
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1">
            Стоимость транспортировки до границы РК (KZT)
          </label>
          <input
            type="number"
            required
            min="0"
            value={transportCost}
            onChange={(e) => onTransportCostChange(parseFloat(e.target.value) || 0)}
            className="block w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-slate-900 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/10 focus:outline-none text-sm transition-all"
          />
        </div>

        {/* HS Parameters Row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">
              Импортная пошлина (%)
            </label>
            <input
              type="number"
              required
              min="0"
              max="100"
              step="0.01"
              value={dutyRate}
              onChange={(e) => onDutyRateChange(parseFloat(e.target.value) || 0)}
              className="block w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-slate-900 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/10 focus:outline-none text-sm transition-all"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">
              Ставка акциза (%)
            </label>
            <input
              type="number"
              required
              min="0"
              max="100"
              step="0.01"
              value={exciseRate}
              onChange={(e) => onExciseRateChange(parseFloat(e.target.value) || 0)}
              className="block w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-slate-900 focus:border-teal-500 focus:ring-2 focus:ring-teal-500/10 focus:outline-none text-sm transition-all"
            />
          </div>
        </div>
        {/* Recycling Fee checkbox */}
        <div className="flex items-center space-x-2 pt-2">
          <input
            type="checkbox"
            id="isRecycling"
            checked={isRecycling}
            onChange={(e) => onRecyclingChange(e.target.checked)}
            className="rounded border-slate-300 text-teal-600 focus:ring-teal-500 h-4.5 w-4.5 cursor-pointer accent-teal-600"
          />
          <label
            htmlFor="isRecycling"
            className="text-sm text-slate-700 font-medium select-none cursor-pointer"
          >
            Облагается утилизационным сбором (утильсбор)
          </label>
        </div>

        {/* Calculate Button */}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-brand-teal hover:bg-brand-teal-hover text-white font-semibold py-3 px-4 rounded-xl shadow-xs hover:shadow transition-colors duration-150 text-sm disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed cursor-pointer"
        >
          {loading ? "Рассчитываем..." : "Рассчитать таможенные платежи"}
        </button>
      </form>
    </section>
  );
}
