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
    <header className="bg-white/90 backdrop-blur-md sticky top-0 z-50 text-slate-900 shadow-xs border-b border-blue-100 transition-all duration-300">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-gradient-to-br from-blue-600 to-cyan-600 p-2.5 rounded-xl text-white shadow-md shadow-blue-500/10">
            <Calculator className="h-5 w-5" />
          </div>
          <div>
            <span className="font-extrabold text-xl tracking-tight bg-gradient-to-r from-blue-900 via-blue-850 to-cyan-700 bg-clip-text text-transparent block">
              Кеден Көмекшісі
            </span>
            <span className="text-[10px] font-bold tracking-wider uppercase text-cyan-600 block">
              AI Customs Assistant RK
            </span>
          </div>
        </div>

        {/* NBK Exchange Rates Live Feed */}
        <div className="hidden md:flex items-center space-x-3 bg-slate-50/80 px-4 py-1.5 rounded-xl text-xs border border-slate-200/80 shadow-xs">
          <span className="flex items-center text-slate-500 font-semibold">
            <TrendingUp className="h-3.5 w-3.5 text-blue-600 mr-1.5" />
            Курсы НБРК:
          </span>
          <div className="flex space-x-2 text-slate-600">
            <span className="bg-white px-3 py-1 rounded-lg border border-slate-200/60 shadow-xs tabular-nums font-medium">
              USD <span className="text-blue-600 font-bold ml-1">{rates.USD?.toFixed(2)} ₸</span>
            </span>
            <span className="bg-white px-3 py-1 rounded-lg border border-slate-200/60 shadow-xs tabular-nums font-medium">
              EUR <span className="text-blue-600 font-bold ml-1">{rates.EUR?.toFixed(2)} ₸</span>
            </span>
            <span className="bg-white px-3 py-1 rounded-lg border border-slate-200/60 shadow-xs tabular-nums font-medium">
              CNY <span className="text-blue-600 font-bold ml-1">{rates.CNY?.toFixed(2)} ₸</span>
            </span>
            <span className="bg-white px-3 py-1 rounded-lg border border-slate-200/60 shadow-xs tabular-nums font-medium">
              RUB <span className="text-blue-600 font-bold ml-1">{rates.RUB?.toFixed(2)} ₸</span>
            </span>
          </div>
          <button
            onClick={onRefreshRates}
            className="text-slate-400 hover:text-blue-600 hover:bg-slate-100 p-1.5 rounded-lg transition-all duration-150 cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-blue-500/30"
            title="Обновить курсы валют"
            aria-label="Обновить курсы валют"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${ratesLoading ? "animate-spin text-blue-600" : ""}`}
            />
          </button>
        </div>
      </div>
    </header>
  );
}
