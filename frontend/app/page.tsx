"use client";

import React, { useState, useEffect, useRef } from "react";
import { 
  Calculator, 
  MessageSquare, 
  Search, 
  TrendingUp, 
  AlertTriangle, 
  CheckCircle, 
  Upload, 
  BookOpen, 
  ShieldAlert,
  MapPin,
  RefreshCw,
  Paperclip
} from "lucide-react";

// Types corresponding to FastAPI backend models
interface ExchangeRates {
  [currency: string]: number;
}

interface CalculationRequest {
  invoice_price: number;
  currency: string;
  exchange_rate: number;
  transport_to_border: number;
  duty_rate_percent: number;
  excise_rate_percent: number;
  excise_specific_rate: number;
  excise_units_count: number;
  is_subject_to_recycling_fee: boolean;
  recycling_fee_base_mci?: number;
}

interface CalculationResponse {
  customs_value_kzt: number;
  customs_fee_kzt: number;
  customs_duty_kzt: number;
  excise_kzt: number;
  import_vat_kzt: number;
  recycling_fee_kzt: number;
  total_payments_kzt: number;
  trois_warning?: string;
}

interface HSCodeCandidate {
  hs_code: string;
  product_name_ru: string;
  duty_rate_percent: number;
  excise_rate_percent: number;
  is_subject_to_recycling_fee: boolean;
  confidence_score: number;
  reasoning: string;
}

interface HSClassificationResponse {
  product_description: string;
  candidates: HSCodeCandidate[];
}

interface LegalChunk {
  document_title: string;
  article_number: string;
  content_quote: string;
  relevance_score: number;
}

interface LegalRAGResponse {
  query: string;
  answer_synthesis: string;
  supporting_laws: LegalChunk[];
}

// Orchestrator types
interface OrchestrateRequest {
  text: string;
  session_id?: string;
}

interface OrchestrateResponse {
  intent: string;
  message: string;
  pipeline_results?: {
    supporting_laws?: LegalChunk[];
    candidates?: HSCodeCandidate[];
  };
  chain_warning?: string;
}

export default function CustomsDashboard() {
  // Common states
  const [sessionId, setSessionId] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    // Generate UUID for Langfuse session grouping
    setSessionId(self.crypto.randomUUID());
  }, []);
  const [exchangeRates, setExchangeRates] = useState<ExchangeRates>({ USD: 450.0, EUR: 485.0, RUB: 5.0, CNY: 62.0, KZT: 1.0 });
  const [ratesLoading, setRatesLoading] = useState<boolean>(false);
  // Calculator form states
  const [invoicePrice, setInvoicePrice] = useState<number>(1000);
  const [currency, setCurrency] = useState<string>("USD");
  const [customRate, setCustomRate] = useState<number>(450);
  const [transportCost, setTransportCost] = useState<number>(50000); // in KZT
  const [dutyRate, setDutyRate] = useState<number>(10);
  const [exciseRate, setExciseRate] = useState<number>(0);
  const [isRecycling, setIsRecycling] = useState<boolean>(false);
  const [calcResult, setCalcResult] = useState<CalculationResponse | null>(null);
  const [calcLoading, setCalcLoading] = useState<boolean>(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  // Unified Chat States
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const [latestProductName, setLatestProductName] = useState<string>("");
  const [latestCandidates, setLatestCandidates] = useState<HSCodeCandidate[] | null>(null);
  const [chatQuery, setChatQuery] = useState<string>("");
  const [chatHistory, setChatHistory] = useState<Array<{ 
    role: "user" | "assistant"; 
    text: string; 
    laws?: LegalChunk[]; 
    candidates?: HSCodeCandidate[];
    calculation?: CalculationResponse;
    chain_warning?: string;
    filePreview?: string;
    fileName?: string;
  }>>([
    {
      role: "assistant",
      text: "Здравствуйте! Я ИИ-консультант «Интеллектуальный Помощник Keden». Я могу подобрать код ТН ВЭД для вашего товара (в том числе по фотографии), проконсультировать по таможенному законодательству РК (RAG по кодексам) и помочь рассчитать таможенные платежи.",
    }
  ]);
  const [chatLoading, setChatLoading] = useState<boolean>(false);

  // Fetch exchange rates from National Bank on mount
  const fetchRates = async () => {
    setRatesLoading(true);
    try {
      const res = await fetch("/api/rates");
      if (res.ok) {
        const data = await res.json();
        setExchangeRates(data);
        if (data[currency]) {
          setCustomRate(data[currency]);
        }
      }
    } catch (e) {
      console.warn("Failed to fetch rates, utilizing cached defaults", e);
    } finally {
      setRatesLoading(false);
    }
  };

  useEffect(() => {
    fetchRates();
  }, []);

  // Update exchange rate input when currency selection changes
  useEffect(() => {
    if (exchangeRates[currency]) {
      setCustomRate(exchangeRates[currency]);
    }
  }, [currency, exchangeRates]);

  // Handle calculation action
  const handleCalculate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCalcLoading(true);
    setCalcError(null);
    try {
      const payload: CalculationRequest = {
        invoice_price: Number(invoicePrice),
        currency,
        exchange_rate: Number(customRate),
        transport_to_border: Number(transportCost),
        duty_rate_percent: Number(dutyRate),
        excise_rate_percent: Number(exciseRate),
        excise_specific_rate: 0,
        excise_units_count: 0,
        is_subject_to_recycling_fee: isRecycling
      };

      const res = await fetch("/api/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error("Calculation API failed");
      const result = await res.json();
      setCalcResult(result);
    } catch (err: any) {
      setCalcError(err.message || "Ошибка при выполнении расчета");
    } finally {
      setCalcLoading(false);
    }
  };

  // Handle image upload and preview
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploadedFile(file);
      setFilePreview(URL.createObjectURL(file));
    }
  };
  // Handle selection of a candidate from the list
  const applyCandidateToCalculator = (candidate: HSCodeCandidate) => {
    setDutyRate(candidate.duty_rate_percent);
    setExciseRate(candidate.excise_rate_percent);
    setIsRecycling(candidate.is_subject_to_recycling_fee);
    // Smooth scroll back to calculator
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  // Handle chat submission via universal orchestrator accepting multipart/form-data
  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatQuery.trim() && !uploadedFile) return;
    const userMessage = chatQuery;
    const currentFile = uploadedFile;
    const currentPreview = filePreview;
    setChatHistory(prev => [
      ...prev,
      { 
        role: "user", 
        text: userMessage || (currentFile ? `[Загружен файл: ${currentFile.name}]` : ""),
        filePreview: currentPreview || undefined,
        fileName: currentFile ? currentFile.name : undefined
      }
    ]);
    setChatQuery("");
    setUploadedFile(null);
    setFilePreview(null);
    setChatLoading(true);
    const historyPayload = chatHistory.slice(-10).map(msg => ({
      role: msg.role,
      content: msg.text,
    }));
    try {
      const formData = new FormData();
      formData.append("text", userMessage || "Классифицировать изображение");
      formData.append("session_id", sessionId);
      formData.append("history", JSON.stringify(historyPayload));
      if (currentFile) {
        formData.append("file", currentFile);
      }
      const res = await fetch("/api/orchestrate", {
        method: "POST",
        body: formData
      });
      if (!res.ok) throw new Error("Orchestrator API failed");
      const data: OrchestrateResponse = await res.json();
      // Extract details from pipeline results if any
      const laws = data.pipeline_results?.supporting_laws;
      const candidates = data.pipeline_results?.candidates;
      const calculation = (data.pipeline_results as any)?.calculation_response;
      if (candidates && candidates.length > 0) {
        setLatestCandidates(candidates);
        setLatestProductName(candidates[0].product_name_ru || userMessage || "Таможенный товар");
      }
      setChatHistory(prev => [
        ...prev,
        {
          role: "assistant",
          text: data.message,
          laws: laws,
          candidates: candidates,
          calculation: calculation,
          chain_warning: data.chain_warning
        }
      ]);
    } catch (err: any) {
      setChatHistory(prev => [
        ...prev,
        {
          role: "assistant",
          text: "Извините, произошла ошибка подключения к серверу или обработки запроса."
        }
      ]);
    } finally {
      setChatLoading(false);
    }
  };
  // Document generation state & handlers
  const [docLoading, setDocLoading] = useState<boolean>(false);
  const handleDownloadInvoice = async () => {
    setDocLoading(true);
    try {
      const payload = {
        seller_name: "FOREIGN VENDOR LTD (Шэньчжэнь, Китай)",
        buyer_name: "TOO KAZAKH IMPORTER (Алматы, Казахстан)",
        incoterms: "FCA Shenzhen",
        items: [
          {
            name: latestProductName.trim() || "Таможенный товар (импорт)",
            hs_code: latestCandidates?.[0]?.hs_code || "8517130000",
            qty: 1,
            unit: "pcs",
            price: Number(invoicePrice)
          }
        ]
      };
      const res = await fetch("/api/generate-excel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Invoice generation failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "Commercial_Invoice.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      console.error(err);
      alert("Ошибка при генерации инвойса");
    } finally {
      setDocLoading(false);
    }
  };
  const handleDownloadContract = async () => {
    setDocLoading(true);
    try {
      const payload = {
        contract_no: "KED-2026/089",
        contract_date: new Date().toLocaleDateString("ru-RU", { day: 'numeric', month: 'long', year: 'numeric' }),
        seller_name: "FOREIGN VENDOR LTD (Китай)",
        buyer_name: "TOO KAZAKH IMPORTER (Казахстан)",
        incoterms: "DDP Almaty"
      };
      const res = await fetch("/api/generate-word", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Contract generation failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "Supply_Agreement.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      console.error(err);
      alert("Ошибка при генерации договора");
    } finally {
      setDocLoading(false);
    }
  };
  return (
    <div className="min-h-screen flex flex-col font-sans">
      {/* Navigation Header */}
      <header className="bg-slate-900 text-white shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="bg-teal-500 p-2 rounded-lg text-white">
              <Calculator className="h-6 w-6" />
            </div>
            <div>
              <span className="font-bold text-xl tracking-tight text-white block">Кеден Көмекшісі</span>
              <span className="text-xs text-slate-400 block -mt-1">AI Customs Assistant RK</span>
            </div>
          </div>
          
          {/* NBK Exchange Rates Live Feed */}
          <div className="hidden md:flex items-center space-x-4 bg-slate-800 px-4 py-2 rounded-lg text-sm border border-slate-700">
            <span className="flex items-center text-slate-400 space-x-1">
              <TrendingUp className="h-4 w-4 text-teal-400 mr-1" />
              Курсы НБРК:
            </span>
            <div className="flex space-x-3 font-semibold text-slate-200">
              <span>USD: <span className="text-teal-400">{exchangeRates.USD?.toFixed(2)} ₸</span></span>
              <span>EUR: <span className="text-teal-400">{exchangeRates.EUR?.toFixed(2)} ₸</span></span>
              <span>CNY: <span className="text-teal-400">{exchangeRates.CNY?.toFixed(2)} ₸</span></span>
              <span>RUB: <span className="text-teal-400">{exchangeRates.RUB?.toFixed(2)} ₸</span></span>
            </div>
            <button 
              onClick={fetchRates} 
              className="text-slate-400 hover:text-white transition duration-150 ml-1 cursor-pointer"
              title="Обновить курсы валют"
            >
              <RefreshCw className={`h-4 w-4 ${ratesLoading ? 'animate-spin text-teal-400' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      {/* Main Body Grid */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column: Customs Calculator (5/12 span) */}
        <section className="lg:col-span-5 bg-white border border-slate-200 rounded-2xl shadow-sm p-6 flex flex-col h-fit">
          <div className="flex items-center space-x-2 border-b border-slate-100 pb-4 mb-6">
            <Calculator className="h-5 w-5 text-teal-600" />
            <h2 className="font-bold text-lg text-slate-800">Калькулятор платежей</h2>
          </div>

          <form onSubmit={handleCalculate} className="space-y-4">
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
                  onChange={(e) => setInvoicePrice(parseFloat(e.target.value) || 0)}
                  className="block w-full rounded-l-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
                  placeholder="Например, 1500"
                />
                <select
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
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
                  onChange={(e) => setCustomRate(parseFloat(e.target.value) || 1)}
                  className="block w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
                />
              </div>
            )}

            {/* Transport costs to RK Border */}
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">
                Стоимость транспортировки до границы РК (KZT)
              </label>
              <input
                type="number"
                required
                min="0"
                value={transportCost}
                onChange={(e) => setTransportCost(parseFloat(e.target.value) || 0)}
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
                  onChange={(e) => setDutyRate(parseFloat(e.target.value) || 0)}
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
                  onChange={(e) => setExciseRate(parseFloat(e.target.value) || 0)}
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
                onChange={(e) => setIsRecycling(e.target.checked)}
                className="rounded border-slate-300 text-teal-600 focus:ring-teal-500 h-4 w-4"
              />
              <label htmlFor="isRecycling" className="text-sm text-slate-700 font-medium select-none cursor-pointer">
                Облагается утилизационным сбором (утильсбор)
              </label>
            </div>

            {/* Calculate Button */}
            <button
              type="submit"
              disabled={calcLoading}
              className="w-full bg-teal-600 hover:bg-teal-700 text-white font-bold py-2 px-4 rounded-lg shadow-sm transition duration-150 text-sm disabled:bg-slate-300 disabled:cursor-not-allowed cursor-pointer"
            >
              {calcLoading ? "Рассчитываем..." : "Рассчитать таможенные платежи"}
            </button>
          </form>

          {/* Calculation Error Block */}
          {calcError && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs flex items-center space-x-2">
              <AlertTriangle className="h-4 w-4 text-red-500 shrink-0" />
              <span>{calcError}</span>
            </div>
          )}

          {/* Deterministic Results Area */}
          {calcResult && (
            <div className="mt-6 border-t border-slate-200 pt-6 space-y-4">
              <h3 className="font-bold text-slate-800 text-sm tracking-wide uppercase">Детализация платежей (Тенге)</h3>
              
              <div className="space-y-2 text-sm bg-slate-50 p-4 rounded-xl border border-slate-100">
                <div className="flex justify-between">
                  <span className="text-slate-500">Таможенная стоимость (СВ):</span>
                  <span className="font-semibold text-slate-800">{calcResult.customs_value_kzt.toLocaleString()} ₸</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Таможенный сбор (фиксированный):</span>
                  <span className="font-semibold text-slate-800">{calcResult.customs_fee_kzt.toLocaleString()} ₸</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Импортная пошлина ({dutyRate}%):</span>
                  <span className="font-semibold text-slate-800">{calcResult.customs_duty_kzt.toLocaleString()} ₸</span>
                </div>
                {exciseRate > 0 && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Акциз ({exciseRate}%):</span>
                    <span className="font-semibold text-slate-800">{calcResult.excise_kzt.toLocaleString()} ₸</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-slate-500">Импортный НДС (12%):</span>
                  <span className="font-semibold text-slate-800">{calcResult.import_vat_kzt.toLocaleString()} ₸</span>
                </div>
                {calcResult.recycling_fee_kzt > 0 && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Утилизационный сбор:</span>
                    <span className="font-semibold text-slate-800">{calcResult.recycling_fee_kzt.toLocaleString()} ₸</span>
                  </div>
                )}
                
                {/* Total payments summary */}
                <div className="flex justify-between border-t border-slate-200 pt-3 mt-2 text-base font-bold text-slate-950">
                  <span>Итого к уплате:</span>
                  <span className="text-teal-600">{calcResult.total_payments_kzt.toLocaleString()} ₸</span>
                </div>
              </div>

              {/* Intellectual Property alert (TROIS) */}
              {calcResult.trois_warning && (
                <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg text-xs flex items-start space-x-2">
                  <ShieldAlert className="h-5 w-5 text-amber-600 shrink-0" />
                  <div>
                    <span className="font-bold">Внимание ТРОИС:</span> {calcResult.trois_warning}
                  </div>
                </div>
              )}
              {/* Document Download Section */}
              <div className="pt-4 border-t border-slate-100 flex flex-col space-y-2">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Экспорт документов</span>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={handleDownloadInvoice}
                    disabled={docLoading}
                    className="flex items-center justify-center space-x-1.5 border border-slate-300 hover:border-teal-500 hover:text-teal-600 text-slate-700 bg-white px-3 py-2 rounded-lg text-xs font-bold transition duration-150 cursor-pointer disabled:opacity-50"
                  >
                    <span>📊 Скачать Инвойс (Excel)</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleDownloadContract}
                    disabled={docLoading}
                    className="flex items-center justify-center space-x-1.5 border border-slate-300 hover:border-teal-500 hover:text-teal-600 text-slate-700 bg-white px-3 py-2 rounded-lg text-xs font-bold transition duration-150 cursor-pointer disabled:opacity-50"
                  >
                    <span>📝 Скачать Договор (Word)</span>
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Right Column: Unified Intellect Chat Workspace (7/12 span) */}
        <section className="lg:col-span-7 flex flex-col h-[650px] bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          {/* Header */}
          <div className="bg-slate-50 border-b border-slate-100 px-6 py-4 flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="bg-teal-500/10 p-2 rounded-lg text-teal-600">
                <MessageSquare className="h-5 w-5" />
              </div>
              <div>
                <h3 className="font-bold text-slate-800 text-base">«Интеллектуальный Помощник Keden»</h3>
                <p className="text-xs text-slate-500">Мультимодальный подбор кодов ТН ВЭД, правовой RAG и расчеты</p>
              </div>
            </div>
            {/* Session ID display / Reset indicator */}
            <div className="text-[10px] bg-slate-200/60 text-slate-600 px-2 py-1 rounded font-mono">
              SESS: {sessionId.substring(0, 8)}...
            </div>
          </div>
          {/* Chat Feed */}
          <div className="flex-1 overflow-y-auto p-6 space-y-4 text-sm bg-slate-50/50">
            {chatHistory.map((msg, idx) => (
              <div 
                key={idx} 
                className={`flex flex-col max-w-[85%] rounded-2xl p-4 shadow-sm border ${
                  msg.role === "user" 
                    ? "bg-teal-600 border-teal-500 text-white self-end ml-auto rounded-tr-none" 
                    : "bg-white border-slate-100 text-slate-950 self-start rounded-tl-none"
                }`}
              >
                <span className={`font-bold text-[10px] uppercase tracking-wider mb-1 select-none ${
                  msg.role === "user" ? "text-teal-200" : "text-teal-600"
                }`}>
                  {msg.role === "user" ? "Вы" : "ИИ Keden"}
                </span>
                {/* User file attachment preview inside the bubble */}
                {msg.filePreview && (
                  <div className="mb-2 rounded-lg overflow-hidden border border-black/10 max-w-xs bg-black/5">
                    <img 
                      src={msg.filePreview} 
                      alt="Attachment preview" 
                      className="max-h-40 w-auto object-contain mx-auto"
                    />
                    {msg.fileName && (
                      <div className="bg-black/20 px-2 py-1 text-xs text-center font-mono truncate text-white">
                        {msg.fileName}
                      </div>
                    )}
                  </div>
                )}
                <p className="whitespace-pre-line leading-relaxed text-sm">{msg.text}</p>
                {/* Context chaining warning block */}
                {msg.chain_warning && (
                  <div className="mt-3 border-t border-slate-100 pt-2.5 text-xs">
                    <div className="flex items-center space-x-1.5 text-amber-600 font-bold mb-1">
                      <TrendingUp className="h-3.5 w-3.5" />
                      <span>Связывание контекста:</span>
                    </div>
                    <p className="bg-amber-50 p-2.5 rounded-lg border border-amber-100/50 text-[11px] leading-relaxed italic text-amber-800">
                      {msg.chain_warning}
                    </p>
                  </div>
                )}
                {/* HS classification cards displayed beautifully inside bubble stream */}
                {msg.candidates && msg.candidates.length > 0 && (
                  <div className="mt-4 border-t border-slate-100 pt-3 space-y-3">
                    <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide block">Рекомендуемые коды ТН ВЭД:</span>
                    {msg.candidates.map((candidate, cIdx) => (
                      <div 
                        key={cIdx} 
                        className="bg-slate-50 border border-slate-100 rounded-xl p-3 text-slate-800 text-xs transition hover:border-teal-200"
                      >
                        <div className="flex items-start justify-between mb-1.5">
                          <div>
                            <span className="inline-block bg-teal-100 text-teal-800 text-[10px] font-bold px-1.5 py-0.5 rounded mr-1.5">
                              Код {candidate.hs_code}
                            </span>
                            <span className="font-bold text-slate-800 text-xs">{candidate.product_name_ru}</span>
                          </div>
                          <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded shrink-0">
                            {(candidate.confidence_score * 100).toFixed(0)}% совпадение
                          </span>
                        </div>
                        <p className="text-slate-500 text-[11px] leading-normal mb-2">{candidate.reasoning}</p>
                        <div className="flex items-center justify-between border-t border-slate-200/40 pt-2 text-[10px]">
                          <span className="text-slate-500">Пошлина: <span className="font-bold text-slate-700">{candidate.duty_rate_percent}%</span></span>
                          <button
                            onClick={() => applyCandidateToCalculator(candidate)}
                            className="text-teal-600 hover:text-teal-800 font-bold transition flex items-center space-x-1 cursor-pointer"
                          >
                            <CheckCircle className="h-3.5 w-3.5" />
                            <span>Применить к расчету</span>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {/* Duty Calculation details displayed beautifully inside bubble stream */}
                {msg.calculation && (
                  <div className="mt-4 border-t border-slate-100 pt-3 space-y-2">
                    <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide block">Расчет таможенных платежей:</span>
                    <div className="bg-slate-50 border border-slate-100 rounded-xl p-3.5 text-slate-800 text-xs space-y-1.5">
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-500">Таможенная стоимость:</span>
                        <span className="font-semibold">{msg.calculation.customs_value_kzt?.toLocaleString()} ₸</span>
                      </div>
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-500">Пошлина:</span>
                        <span className="font-semibold">{msg.calculation.customs_duty_kzt?.toLocaleString()} ₸</span>
                      </div>
                      {msg.calculation.excise_kzt > 0 && (
                        <div className="flex justify-between text-[11px]">
                          <span className="text-slate-500">Акциз:</span>
                          <span className="font-semibold">{msg.calculation.excise_kzt?.toLocaleString()} ₸</span>
                        </div>
                      )}
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-500">Импортный НДС:</span>
                        <span className="font-semibold">{msg.calculation.import_vat_kzt?.toLocaleString()} ₸</span>
                      </div>
                      {msg.calculation.recycling_fee_kzt > 0 && (
                        <div className="flex justify-between text-[11px]">
                          <span className="text-slate-500">Утильсбор:</span>
                          <span className="font-semibold">{msg.calculation.recycling_fee_kzt?.toLocaleString()} ₸</span>
                        </div>
                      )}
                      <div className="flex justify-between border-t border-slate-200/50 pt-2 mt-1.5 font-bold text-teal-700">
                        <span>Итого платежей:</span>
                        <span>{msg.calculation.total_payments_kzt?.toLocaleString()} ₸</span>
                      </div>
                    </div>
                  </div>
                )}
                {/* Citations/Supporting Laws */}
                {msg.laws && msg.laws.length > 0 && (
                  <div className="mt-4 border-t border-slate-100 pt-3 space-y-1.5 text-xs text-slate-800">
                    <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide block">Официальные ссылки:</span>
                    {msg.laws.map((law, lIdx) => (
                      <details key={lIdx} className="bg-slate-50 rounded-xl border border-slate-100 p-2.5 cursor-pointer">
                        <summary className="font-semibold text-teal-800 hover:underline">
                          {law.document_title}, {law.article_number}
                        </summary>
                        <p className="mt-1.5 text-slate-600 bg-white p-2 rounded-lg text-[11px] leading-relaxed border-l-2 border-teal-500 select-all italic font-serif">
                          "{law.content_quote}"
                        </p>
                      </details>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {/* Chat Loading state */}
            {chatLoading && (
              <div className="bg-white border border-slate-100 rounded-2xl p-4 text-slate-500 text-xs self-start flex items-center space-x-2 shadow-sm max-w-[85%] rounded-tl-none">
                <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce" />
                <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce [animation-delay:0.2s]" />
                <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce [animation-delay:0.4s]" />
                <span>ИИ Keden анализирует ваш запрос...</span>
              </div>
            )}
          </div>
          {/* Chat Form Area */}
          <div className="p-4 border-t border-slate-100 bg-white flex flex-col space-y-2">
            {/* Uploaded file preview strip above the input box */}
            {filePreview && (
              <div className="flex items-center space-x-3 p-2 bg-slate-50 border border-slate-200/60 rounded-xl max-w-md">
                <div className="relative shrink-0">
                  <img 
                    src={filePreview} 
                    alt="File thumbnail" 
                    className="h-10 w-10 object-cover rounded border border-slate-200"
                  />
                  <button 
                    type="button"
                    onClick={() => { setUploadedFile(null); setFilePreview(null); }}
                    className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full h-4 w-4 flex items-center justify-center text-[10px] font-bold hover:bg-red-600 cursor-pointer"
                  >
                    ✕
                  </button>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-slate-700 truncate">{uploadedFile?.name}</p>
                  <p className="text-[10px] text-slate-400 font-mono">{(uploadedFile?.size ? uploadedFile.size / 1024 : 0).toFixed(1)} KB</p>
                </div>
              </div>
            )}
            <form onSubmit={handleChatSubmit} className="flex items-center space-x-2">
              {/* Permanent file upload button (paperclip) */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="p-2.5 text-slate-500 hover:text-teal-600 hover:bg-slate-50 rounded-lg border border-slate-200 transition shrink-0 cursor-pointer"
                title="Прикрепить фото товара для классификации"
              >
                <Paperclip className="h-5 w-5" />
              </button>
              <input 
                type="file" 
                ref={fileInputRef}
                accept="image/*" 
                onChange={handleFileChange} 
                className="hidden" 
              />
              <input
                type="text"
                required={!uploadedFile}
                value={chatQuery}
                onChange={(e) => setChatQuery(e.target.value)}
                placeholder="Спросите Keden о ТН ВЭД, законодательстве или прикрепите фото..."
                className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 text-sm focus:border-teal-500 focus:outline-none placeholder-slate-400"
              />
              <button
                type="submit"
                disabled={chatLoading || (!chatQuery.trim() && !uploadedFile)}
                className="bg-teal-600 hover:bg-teal-700 text-white font-bold px-5 py-2.5 rounded-lg text-sm transition duration-150 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed shrink-0 cursor-pointer"
              >
                Отправить
              </button>
            </form>
          </div>
        </section>
      </main>

      {/* Footer information bar */}
      <footer className="bg-slate-900 text-slate-400 text-center py-6 mt-12 border-t border-slate-800 text-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p>© 2026 CustomAI Kazakhstan (Кеден Көмекшісі). Все права защищены. Все расчеты проводятся детерминированно в соответствии с налоговым и таможенным законодательством Республики Казахстан.</p>
        </div>
      </footer>
    </div>
  );
}
