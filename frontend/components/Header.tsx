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
    <header className="bg-slate-950/95 backdrop-blur-md sticky top-0 z-50 text-white shadow-lg border-b border-slate-900 transition-all duration-300">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-gradient-to-br from-teal-400 to-teal-600 p-2.5 rounded-xl text-white shadow-md shadow-teal-500/10">
            <Calculator className="h-5 w-5" />
          </div>
          <div>
            <span className="font-extrabold text-xl tracking-tight bg-gradient-to-r from-white via-slate-100 to-teal-300 bg-clip-text text-transparent block">
              Кеден Көмекшісі
            </span>
            <span className="text-[10px] font-medium tracking-wider uppercase text-teal-400/90 block">
              AI Customs Assistant RK
            </span>
          </div>
        </div>

        {/* NBK Exchange Rates Live Feed */}
        <div className="hidden md:flex items-center space-x-3.5 bg-slate-900/90 px-4 py-1.5 rounded-full text-xs border border-slate-800/80 shadow-inner">
          <span className="flex items-center text-slate-400 font-medium">
            <TrendingUp className="h-3.5 w-3.5 text-teal-400 mr-1.5" />
            Курсы НБРК:
          </span>
          <div className="flex space-x-3 text-slate-300">
            <span className="bg-slate-950 px-2.5 py-0.5 rounded-full border border-slate-800/50">
              USD <span className="text-teal-400 font-semibold ml-1">{rates.USD?.toFixed(2)} ₸</span>
            </span>
            <span className="bg-slate-950 px-2.5 py-0.5 rounded-full border border-slate-800/50">
              EUR <span className="text-teal-400 font-semibold ml-1">{rates.EUR?.toFixed(2)} ₸</span>
            </span>
            <span className="bg-slate-950 px-2.5 py-0.5 rounded-full border border-slate-800/50">
              CNY <span className="text-teal-400 font-semibold ml-1">{rates.CNY?.toFixed(2)} ₸</span>
            </span>
            <span className="bg-slate-950 px-2.5 py-0.5 rounded-full border border-slate-800/50">
              RUB <span className="text-teal-400 font-semibold ml-1">{rates.RUB?.toFixed(2)} ₸</span>
            </span>
          </div>
          <button
            onClick={onRefreshRates}
            className="text-slate-400 hover:text-teal-400 hover:bg-slate-800 p-1 rounded-full transition duration-150 cursor-pointer"
            title="Обновить курсы валют"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${ratesLoading ? "animate-spin text-teal-400" : ""}`}
            />
          </button>
        </div>
      </div>
    </header>
  );
}
