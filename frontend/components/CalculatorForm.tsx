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
    <section className="lg:col-span-5 bg-white border border-slate-200 rounded-2xl shadow-sm p-6 flex flex-col h-fit">
      <div className="flex items-center space-x-2 border-b border-slate-100 pb-4 mb-6">
        <Calculator className="h-5 w-5 text-teal-600" />
        <h2 className="font-bold text-lg text-slate-800">Калькулятор платежей</h2>
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        {/* Invoice Price */}
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
              className="block w-full rounded-l-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
              placeholder="Например, 1500"
            />
            <select
              value={currency}
              onChange={(e) => onCurrencyChange(e.target.value)}
              className="rounded-r-md border border-l-0 border-slate-300 bg-slate-50 px-3 py-2 text-slate-700 text-sm focus:border-teal-500 focus:outline-none"
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
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
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
            className="block w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
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
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
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
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
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
            className="rounded border-slate-300 text-teal-600 focus:ring-teal-500 h-4 w-4"
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
          className="w-full bg-teal-600 hover:bg-teal-700 text-white font-bold py-2 px-4 rounded-lg shadow-sm transition duration-150 text-sm disabled:bg-slate-300 disabled:cursor-not-allowed cursor-pointer"
        >
          {loading ? "Рассчитываем..." : "Рассчитать таможенные платежи"}
        </button>
      </form>
    </section>
  );
}
