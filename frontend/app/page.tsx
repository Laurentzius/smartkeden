"use client";

import React, { useState, useEffect } from "react";
import type { HSCodeCandidate, OrchestrateResponse } from "@/types/api";
import { orchestrate } from "@/lib/api";

import { useExchangeRates } from "@/hooks/useExchangeRates";
import { useCalculator } from "@/hooks/useCalculator";
import { useChat } from "@/hooks/useChat";
import { useDocumentExport } from "@/hooks/useDocumentExport";

import { Header } from "@/components/Header";
import { CalculatorForm } from "@/components/CalculatorForm";
import { CalculationResult } from "@/components/CalculationResult";
import { ChatWorkspace } from "@/components/ChatWorkspace";
import { Footer } from "@/components/Footer";

export default function CustomsDashboard() {
  // ── Session ───────────────────────────────────────────────────────────────
  const [sessionId, setSessionId] = useState<string>("");
  useEffect(() => {
    setSessionId(self.crypto.randomUUID());
  }, []);

  // ── Hooks ─────────────────────────────────────────────────────────────────
  const calc = useCalculator();
  const { loading: docLoading, exportInvoice, exportContract } = useDocumentExport();
  const chat = useChat(sessionId);

  // ── Latest context for document export ────────────────────────────────────
  const [latestProductName, setLatestProductName] = useState("");
  const [latestCandidates, setLatestCandidates] = useState<HSCodeCandidate[] | null>(null);
  const { rates, loading: ratesLoading, refresh: refreshRates } = useExchangeRates();
  useEffect(() => {
    if (rates[calc.currency]) {
      calc.setCustomRate(rates[calc.currency]);
    }
  }, [calc.currency, rates]);

  // ── Apply HS candidate to calculator ──────────────────────────────────────
  const handleApplyCandidate = (candidate: HSCodeCandidate) => {
    calc.applyCandidate(
      candidate.duty_rate_percent,
      candidate.excise_rate_percent,
      candidate.is_subject_to_recycling_fee,
    );
  };

  // ── Chat submit → orchestrator ────────────────────────────────────────────
  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chat.query.trim() && !chat.file) return;

    const userMessage = chat.query;
    const currentFile = chat.file;
    const currentPreview = chat.filePreview;

    chat.appendMessage({
      role: "user",
      text:
        userMessage ||
        (currentFile ? `[Загружен файл: ${currentFile.name}]` : ""),
      filePreview: currentPreview || undefined,
      fileName: currentFile ? currentFile.name : undefined,
    });

    chat.setQuery("");
    chat.clearFile();
    chat.setLoading(true);

    const historyPayload = chat.history.slice(-10).map((msg) => ({
      role: msg.role,
      content: msg.text,
    }));

    try {
      const data: OrchestrateResponse = await orchestrate(
        userMessage || "",
        sessionId,
        historyPayload,
        currentFile ?? undefined,
      );

      const laws = data.pipeline_results?.supporting_laws;
      const candidates = data.pipeline_results?.candidates;
      const calculation = data.pipeline_results?.calculation_response;

      if (candidates && candidates.length > 0) {
        setLatestCandidates(candidates);
        setLatestProductName(
          candidates[0].product_name_ru || userMessage || "Таможенный товар",
        );
      }

      chat.appendMessage({
        role: "assistant",
        text: data.message,
        laws,
        candidates,
        calculation,
        chain_warning: data.chain_warning,
      });
    } catch {
      chat.appendMessage({
        role: "assistant",
        text: "Извините, произошла ошибка подключения к серверу или обработки запроса.",
      });
    } finally {
      chat.setLoading(false);
    }
  };

  // ── Document export handlers ──────────────────────────────────────────────
  const handleExportInvoice = () => {
    exportInvoice(
      latestProductName,
      latestCandidates?.[0]?.hs_code || "8517130000",
      calc.invoicePrice,
    );
  };

  const handleExportContract = () => {
    exportContract();
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col font-sans">
      <Header
        rates={rates}
        ratesLoading={ratesLoading}
        onRefreshRates={refreshRates}
        sessionId={sessionId}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Calculator & Calculation Results */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          <CalculatorForm
            invoicePrice={calc.invoicePrice}
            onInvoicePriceChange={calc.setInvoicePrice}
            currency={calc.currency}
            onCurrencyChange={calc.setCurrency}
            customRate={calc.customRate}
            onCustomRateChange={calc.setCustomRate}
            transportCost={calc.transportCost}
            onTransportCostChange={calc.setTransportCost}
            dutyRate={calc.dutyRate}
            onDutyRateChange={calc.setDutyRate}
            exciseRate={calc.exciseRate}
            onExciseRateChange={calc.setExciseRate}
            isRecycling={calc.isRecycling}
            onRecyclingChange={calc.setIsRecycling}
            loading={calc.loading}
            onSubmit={calc.calculate}
          />

          {(calc.result || calc.error) && (
            <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm p-6 transition-all duration-200 hover:shadow-md hover:border-slate-200">
              <CalculationResult
                result={calc.result}
                error={calc.error}
                dutyRate={calc.dutyRate}
                exciseRate={calc.exciseRate}
                docLoading={docLoading}
                onExportInvoice={handleExportInvoice}
                onExportContract={handleExportContract}
              />
            </div>
          )}
        </div>

        {/* Right Column: Intelligent Chat Assistant */}
        <div className="lg:col-span-7">
          <ChatWorkspace
            sessionId={sessionId}
            history={chat.history}
            loading={chat.loading}
            query={chat.query}
            onQueryChange={chat.setQuery}
            onSubmit={handleChatSubmit}
            filePreview={chat.filePreview}
            file={chat.file}
            fileInputRef={chat.fileInputRef}
            onFileChange={chat.handleFileChange}
            onClearFile={chat.clearFile}
            onApplyCandidate={handleApplyCandidate}
          />
        </div>
      </main>

      <Footer />
    </div>
  );
}
