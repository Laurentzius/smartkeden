"use client";

import React, { useState, useEffect } from "react";
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
  RefreshCw
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
  const [activeTab, setActiveTab] = useState<"classifier" | "rag">("classifier");
  const [sessionId, setSessionId] = useState<string>("");

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

  // HS Classifier states
  const [productDesc, setProductDesc] = useState<string>("");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const [classificationResult, setClassificationResult] = useState<HSClassificationResponse | null>(null);
  const [classLoading, setClassLoading] = useState<boolean>(false);
  const [classError, setClassError] = useState<string | null>(null);

  // Legal RAG states
  const [ragQuery, setRagQuery] = useState<string>("");
  const [ragHistory, setRagHistory] = useState<Array<{ role: "user" | "assistant"; text: string; laws?: LegalChunk[]; chain_warning?: string }>>([
    {
      role: "assistant",
      text: "Здравствуйте! Я ИИ-консультант Кеден Көмекшісі. Задайте мне любой вопрос о таможенном кодексе РК, ставках налогов или требованиях к импорту.",
    }
  ]);
  const [ragLoading, setRagLoading] = useState<boolean>(false);


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

  // Handle HS classification action
  const handleClassify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!productDesc.trim()) return;
    setClassLoading(true);
    setClassError(null);
    try {
      const formData = new FormData();
      formData.append("description", productDesc);
      if (uploadedFile) {
        formData.append("file", uploadedFile);
      }

      const res = await fetch("/api/classify", {
        method: "POST",
        body: formData
      });

      if (!res.ok) throw new Error("Classification API failed");
      const result = await res.json();
      setClassificationResult(result);
    } catch (err: any) {
      setClassError(err.message || "Ошибка классификации");
    } finally {
      setClassLoading(false);
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

  // Handle chat submission via universal orchestrator
  const handleRagSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ragQuery.trim()) return;
    const userMessage = ragQuery;
    setRagHistory(prev => [...prev, { role: "user", text: userMessage }]);
    setRagQuery("");
    setRagLoading(true);

    const historyPayload = ragHistory.slice(-10).map(msg => ({
      role: msg.role,
      content: msg.text,
    }));

    try {
    const res = await fetch("/api/orchestrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: userMessage,
        session_id: sessionId,
        history: historyPayload,
      })
    });

      if (!res.ok) throw new Error("Orchestrator API failed");
      const data: OrchestrateResponse = await res.json();

      setRagHistory(prev => [
        ...prev,
        {
          role: "assistant",
          text: data.message,
          laws: data.pipeline_results?.supporting_laws,
          chain_warning: data.chain_warning
        }
      ]);
    } catch (err: any) {
      setRagHistory(prev => [
        ...prev,
        {
          role: "assistant",
          text: "Извините, произошла ошибка подключения к серверу."
        }
      ]);
    } finally {
      setRagLoading(false);
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

            </div>
          )}
        </section>

        {/* Right Column: Ingestion/Classifier + Legal RAG Workspace (7/12 span) */}
        <section className="lg:col-span-7 flex flex-col h-fit space-y-6">
          
          {/* Navigation Tab bar */}
          <div className="flex border-b border-slate-200">
            <button
              onClick={() => setActiveTab("classifier")}
              className={`flex items-center space-x-2 py-3 px-6 font-bold text-sm tracking-wide transition border-b-2 cursor-pointer ${
                activeTab === "classifier"
                  ? "border-teal-500 text-teal-600"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <Search className="h-4 w-4" />
              <span>ИИ-Подбор ТН ВЭД</span>
            </button>
            <button
              onClick={() => setActiveTab("rag")}
              className={`flex items-center space-x-2 py-3 px-6 font-bold text-sm tracking-wide transition border-b-2 cursor-pointer ${
                activeTab === "rag"
                  ? "border-teal-500 text-teal-600"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <MessageSquare className="h-4 w-4" />
              <span>Правовой RAG Чат</span>
            </button>
          </div>

          {/* Tab 1: Multimodal HS Code Classifier */}
          {activeTab === "classifier" && (
            <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 space-y-6 animate-fadeIn">
              <div className="flex items-center space-x-2 border-b border-slate-100 pb-3">
                <Search className="h-5 w-5 text-teal-600" />
                <h3 className="font-bold text-slate-800">ИИ-Классификатор ТН ВЭД (10 цифр)</h3>
              </div>

              <form onSubmit={handleClassify} className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">
                    Описание товара (на русском или казахском)
                  </label>
                  <textarea
                    rows={3}
                    required
                    value={productDesc}
                    onChange={(e) => setProductDesc(e.target.value)}
                    className="block w-full rounded-md border border-slate-300 px-3 py-2 text-slate-900 focus:border-teal-500 focus:outline-none text-sm"
                    placeholder="Пример: Пластиковые детские конструкторы Lego, состоящие из цветных кубиков, в картонной коробке для сборки моделей..."
                  />
                </div>

                {/* Multimodal Image Input */}
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">
                    Фото товара (необязательно, для ИИ-анализа зрения)
                  </label>
                  <div className="flex items-center space-x-4">
                    <label className="flex flex-col items-center justify-center border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-teal-500 p-4 w-40 text-center transition duration-150">
                      <Upload className="h-6 w-6 text-slate-400 mb-1" />
                      <span className="text-xs text-slate-600">Загрузить фото</span>
                      <input 
                        type="file" 
                        accept="image/*" 
                        onChange={handleFileChange} 
                        className="hidden" 
                      />
                    </label>
                    
                    {filePreview && (
                      <div className="relative">
                        <img 
                          src={filePreview} 
                          alt="Product preview" 
                          className="h-20 w-20 object-cover rounded-lg border border-slate-200 shadow-sm"
                        />
                        <button 
                          type="button"
                          onClick={() => { setUploadedFile(null); setFilePreview(null); }}
                          className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 text-xs hover:bg-red-600 cursor-pointer"
                        >
                          ✕
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={classLoading}
                  className="bg-teal-600 hover:bg-teal-700 text-white font-bold py-2 px-4 rounded-lg text-sm shadow-sm transition duration-150 disabled:bg-slate-300 disabled:cursor-not-allowed cursor-pointer"
                >
                  {classLoading ? "Классифицируем..." : "Определить код ТН ВЭД"}
                </button>
              </form>

              {classError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs flex items-center space-x-2">
                  <AlertTriangle className="h-4 w-4 text-red-500" />
                  <span>{classError}</span>
                </div>
              )}

              {/* Classification Candidates Result */}
              {classificationResult && (
                <div className="space-y-4 pt-4 border-t border-slate-100">
                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span>Распознано ИИ:</span>
                    <span className="font-semibold text-slate-800">Найдены соответствия</span>
                  </div>
                  
                  {classificationResult.candidates.map((candidate, idx) => (
                    <div 
                      key={idx} 
                      className="border border-slate-100 bg-slate-50 rounded-xl p-4 hover:border-teal-200 transition duration-150"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <span className="inline-block bg-teal-100 text-teal-800 text-xs font-bold px-2 py-0.5 rounded mr-2">
                            Код {candidate.hs_code}
                          </span>
                          <span className="font-bold text-slate-800 text-sm">{candidate.product_name_ru}</span>
                        </div>
                        <span className="text-xs font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">
                          {(candidate.confidence_score * 100).toFixed(0)}% совпадение
                        </span>
                      </div>
                      
                      <p className="text-slate-600 text-xs mb-3">{candidate.reasoning}</p>
                      
                      <div className="flex items-center justify-between border-t border-slate-200/50 pt-3 text-xs">
                        <div className="flex space-x-4 text-slate-500">
                          <span>Пошлина: <span className="font-bold text-slate-800">{candidate.duty_rate_percent}%</span></span>
                          {candidate.is_subject_to_recycling_fee && (
                            <span className="text-amber-700 font-semibold flex items-center">
                              <AlertTriangle className="h-3 w-3 mr-1" /> Утильсбор
                            </span>
                          )}
                        </div>
                        <button
                          onClick={() => applyCandidateToCalculator(candidate)}
                          className="text-teal-600 hover:text-teal-800 font-bold transition flex items-center space-x-1 cursor-pointer"
                        >
                          <CheckCircle className="h-4 w-4" />
                          <span>Применить к расчету</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Tab 2: Legal RAG Chat Feed */}
          {activeTab === "rag" && (
            <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 flex flex-col h-[550px] animate-fadeIn">
              <div className="flex items-center space-x-2 border-b border-slate-100 pb-3 mb-4">
                <BookOpen className="h-5 w-5 text-teal-600" />
                <h3 className="font-bold text-slate-800">Нормативная база RAG (Таможенный & Налоговый Кодексы РК)</h3>
              </div>

              {/* Chat history list */}
              <div className="flex-1 overflow-y-auto space-y-4 pr-1 mb-4 text-sm">
                {ragHistory.map((msg, idx) => (
                  <div 
                    key={idx} 
                    className={`flex flex-col max-w-[85%] rounded-xl p-3 ${
                      msg.role === "user" 
                        ? "bg-teal-50 border border-teal-100 text-teal-950 self-end ml-auto" 
                        : "bg-slate-50 border border-slate-100 text-slate-950 self-start"
                    }`}
                  >
                    <span className="font-bold text-xs text-slate-400 mb-1 select-none">
                      {msg.role === "user" ? "Вы" : "ИИ Кеден Көмекшісі"}
                    </span>
                    <p className="whitespace-pre-line leading-relaxed">{msg.text}</p>
                    
                    {/* Context chaining display */}
                    {msg.chain_warning && (
                      <div className="mt-3 border-t border-slate-200/65 pt-2 text-xs text-slate-600">
                        <div className="flex items-center space-x-1.5 text-teal-700 font-bold mb-1">
                          <TrendingUp className="h-3.5 w-3.5" />
                          <span>Связывание контекста:</span>
                        </div>
                        <p className="bg-teal-50/50 p-2 rounded border border-teal-100/50 text-[11px] leading-relaxed italic text-slate-700">
                          {msg.chain_warning}
                        </p>
                      </div>
                    )}

                    {/* Citations/Supporting Laws */}
                    {msg.laws && msg.laws.length > 0 && (
                      <div className="mt-3 border-t border-slate-200/65 pt-2 space-y-1.5">
                        <span className="text-xs font-bold text-slate-500 uppercase tracking-wide block">Официальные ссылки:</span>
                        {msg.laws.map((law, lIdx) => (
                          <details key={lIdx} className="text-xs text-slate-600 bg-white/70 rounded border border-slate-150 p-1.5 cursor-pointer">
                            <summary className="font-semibold text-teal-800 hover:underline">
                              {law.document_title}, {law.article_number}
                            </summary>
                            <p className="mt-1 text-slate-600 bg-slate-50 p-1.5 rounded text-[11px] leading-relaxed border-l-2 border-teal-500 select-all italic">
                              "{law.content_quote}"
                            </p>
                          </details>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                
                {/* Chat Loading state */}
                {ragLoading && (
                  <div className="bg-slate-50 border border-slate-100 rounded-xl p-3 text-slate-500 text-xs self-start flex items-center space-x-2">
                    <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce" />
                    <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce [animation-delay:0.2s]" />
                    <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce [animation-delay:0.4s]" />
                    <span>Поиск по статьям кодексов РК...</span>
                  </div>
                )}
              </div>

              {/* Chat input box */}
              <form onSubmit={handleRagSubmit} className="flex space-x-2">
                <input
                  type="text"
                  required
                  value={ragQuery}
                  onChange={(e) => setRagQuery(e.target.value)}
                  placeholder="Задайте вопрос по таможенному законодательству..."
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-slate-900 text-sm focus:border-teal-500 focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={ragLoading || !ragQuery.trim()}
                  className="bg-teal-600 hover:bg-teal-700 text-white font-bold px-4 py-2 rounded-lg text-sm transition duration-150 disabled:bg-slate-300 disabled:cursor-not-allowed cursor-pointer"
                >
                  Спросить ИИ
                </button>
              </form>
            </div>
          )}
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
