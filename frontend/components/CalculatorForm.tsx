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
    <section className="bg-white/90 backdrop-blur-xs border border-slate-200/60 rounded-2xl shadow-sm p-6 flex flex-col h-fit transition-all duration-200 hover:shadow-md hover:border-slate-200/80">
      <div className="flex items-center space-x-3 border-b border-blue-50 pb-4.5 mb-6">
        <div className="bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-100/80 p-2.5 rounded-xl text-blue-600 shadow-xs">
          <Calculator className="h-5 w-5" />
        </div>
        <h2 className="font-extrabold text-base text-slate-900 tracking-tight text-balance">Калькулятор таможенных платежей</h2>
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-semibold text-slate-800 mb-1.5">
            Фактурная стоимость товара
          </label>
          <div className="relative rounded-xl shadow-xs flex">
            <input
              type="number"
              required
              min="0.01"
              step="any"
              value={invoicePrice}
              onChange={(e) => onInvoicePriceChange(parseFloat(e.target.value) || 0)}
              className="min-h-11 block w-full rounded-l-xl border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-hidden text-sm transition-all"
              placeholder="Например, 1500"
            />
            <select
              value={currency}
              onChange={(e) => onCurrencyChange(e.target.value)}
              className="rounded-r-xl border border-l-0 border-slate-300 bg-slate-50 px-4 py-2.5 text-slate-700 text-sm focus:border-blue-500 focus:outline-hidden cursor-pointer hover:bg-slate-100 transition-colors min-h-11"
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
            <label className="block text-sm font-semibold text-slate-800 mb-1.5">
              Курс валюты к тенге (KZT)
            </label>
            <input
              type="number"
              required
              min="0.01"
              step="any"
              value={customRate}
              onChange={(e) => onCustomRateChange(parseFloat(e.target.value) || 1)}
              className="min-h-11 block w-full rounded-xl border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-hidden text-sm transition-all"
            />
          </div>
        )}

        {/* Transport costs */}
        <div>
          <label className="block text-sm font-semibold text-slate-800 mb-1.5">
            Стоимость транспортировки до границы РК (KZT)
          </label>
          <input
            type="number"
            required
            min="0"
            value={transportCost}
            onChange={(e) => onTransportCostChange(parseFloat(e.target.value) || 0)}
            className="min-h-11 block w-full rounded-xl border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-hidden text-sm transition-all"
          />
        </div>

        {/* HS Parameters Row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-semibold text-slate-800 mb-1.5">
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
              className="min-h-11 block w-full rounded-xl border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-hidden text-sm transition-all"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-800 mb-1.5">
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
              className="min-h-11 block w-full rounded-xl border border-slate-300 px-4 py-2.5 text-slate-900 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-hidden text-sm transition-all"
            />
          </div>
        </div>
        {/* Recycling Fee checkbox */}
        {/* Recycling Fee checkbox */}
        <div className="flex items-center space-x-2.5 pt-2">
          <input
            type="checkbox"
            id="isRecycling"
            checked={isRecycling}
            onChange={(e) => onRecyclingChange(e.target.checked)}
            className="rounded-md border-slate-300 text-blue-600 focus:ring-blue-500/30 h-5 w-5 cursor-pointer accent-blue-600 transition-all focus:ring-2 focus:ring-offset-2"
          />
          <label
            htmlFor="isRecycling"
            className="text-sm text-slate-700 font-semibold select-none cursor-pointer hover:text-slate-900"
          >
            Облагается утилизационным сбором (утильсбор)
          </label>
        </div>

        {/* Calculate Button */}
        <button
          type="submit"
          disabled={loading}
          className="w-full min-h-11 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-bold py-3.5 px-4 rounded-xl shadow-md shadow-blue-500/10 hover:shadow-lg hover:shadow-blue-500/20 transition-all duration-150 text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500/30 active:scale-[0.98] disabled:from-slate-200 disabled:to-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed disabled:scale-100 cursor-pointer flex items-center justify-center"
        >
          {loading ? "Рассчитываем..." : "Рассчитать таможенные платежи"}
        </button>
      </form>
    </section>
  );
}
