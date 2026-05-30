"use client";

import React from "react";
import { Calculator, TrendingUp, RefreshCw } from "lucide-react";
import type { ExchangeRates } from "@/types/api";

interface HeaderProps {
  rates: ExchangeRates;
  ratesLoading: boolean;
  onRefreshRates: () => void;
  sessionId: string;
}

export function Header({ rates, ratesLoading, onRefreshRates, sessionId }: HeaderProps) {
  return (
    <header className="bg-slate-900 text-white shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-teal-500 p-2 rounded-lg text-white">
            <Calculator className="h-6 w-6" />
          </div>
          <div>
            <span className="font-bold text-xl tracking-tight text-white block">
              Кеден Көмекшісі
            </span>
            <span className="text-xs text-slate-400 block -mt-1">
              AI Customs Assistant RK
            </span>
          </div>
        </div>

        {/* NBK Exchange Rates Live Feed */}
        <div className="hidden md:flex items-center space-x-4 bg-slate-800 px-4 py-2 rounded-lg text-sm border border-slate-700">
          <span className="flex items-center text-slate-400 space-x-1">
            <TrendingUp className="h-4 w-4 text-teal-400 mr-1" />
            Курсы НБРК:
          </span>
          <div className="flex space-x-3 font-semibold text-slate-200">
            <span>
              USD: <span className="text-teal-400">{rates.USD?.toFixed(2)} ₸</span>
            </span>
            <span>
              EUR: <span className="text-teal-400">{rates.EUR?.toFixed(2)} ₸</span>
            </span>
            <span>
              CNY: <span className="text-teal-400">{rates.CNY?.toFixed(2)} ₸</span>
            </span>
            <span>
              RUB: <span className="text-teal-400">{rates.RUB?.toFixed(2)} ₸</span>
            </span>
          </div>
          <button
            onClick={onRefreshRates}
            className="text-slate-400 hover:text-white transition duration-150 ml-1 cursor-pointer"
            title="Обновить курсы валют"
          >
            <RefreshCw
              className={`h-4 w-4 ${ratesLoading ? "animate-spin text-teal-400" : ""}`}
            />
          </button>
        </div>
      </div>
    </header>
  );
}
