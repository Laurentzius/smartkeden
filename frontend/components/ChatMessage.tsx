"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import { TrendingUp, CheckCircle } from "lucide-react";
import type { ChatMessage as ChatMessageType, HSCodeCandidate } from "@/types/api";

interface ChatMessageProps {
  msg: ChatMessageType;
  onApplyCandidate?: (candidate: HSCodeCandidate) => void;
}

export function ChatMessage({ msg, onApplyCandidate }: ChatMessageProps) {
  const isUser = msg.role === "user";

  return (
    <div
      className={`flex flex-col max-w-[85%] rounded-2xl p-4 shadow-xs border ${
        isUser
          ? "bg-gradient-to-br from-blue-600 to-cyan-600 border-blue-500/80 text-white self-end ml-auto rounded-tr-none shadow-sm"
          : "bg-white border-slate-200/70 text-slate-950 self-start rounded-tl-none shadow-sm"
      }`}
    >
      <span
        className={`font-bold text-[10px] uppercase tracking-wider mb-1 select-none ${
          isUser ? "text-cyan-100" : "text-blue-600"
        }`}
      >
        {isUser ? "Вы" : "ИИ Keden"}
      </span>

      {/* File preview */}
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

      {msg.text && (
        <div className="prose prose-sm prose-slate max-w-none text-sm leading-relaxed [&_strong]:font-bold [&_em]:italic [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5">
          <ReactMarkdown>{msg.text}</ReactMarkdown>
        </div>
      )}

      {/* Chain warning */}
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

      {/* HS candidates */}
      {msg.candidates && msg.candidates.length > 0 && (
        <div className="mt-4 border-t border-slate-100 pt-3 space-y-3">
          <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide block">
            Рекомендуемые коды ТН ВЭД:
          </span>
          {msg.candidates.map((candidate, cIdx) => (
            <div
              key={cIdx}
              className="bg-slate-50 border border-slate-200/50 rounded-xl p-3 text-slate-800 text-xs transition hover:border-blue-300/80 shadow-xs"
            >
              <div className="flex items-start justify-between mb-1.5">
                <div className="flex items-center flex-wrap gap-1.5">
                  <span className="inline-block bg-blue-50 text-blue-700 text-[10px] font-bold px-1.5 py-0.5 rounded border border-blue-100 tabular-nums">
                    Код {candidate.hs_code}
                  </span>
                  <span className="font-extrabold text-slate-800 text-xs text-balance">
                    {candidate.product_name_ru}
                  </span>
                </div>
                <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-100/50 px-1.5 py-0.5 rounded-md shrink-0 tabular-nums">
                  {(candidate.confidence_score * 100).toFixed(0)}% совпадение
                </span>
              </div>
              <p className="text-slate-600 text-[11px] leading-relaxed mb-2.5 text-pretty">
                {candidate.reasoning}
              </p>
              <div className="flex items-center justify-between border-t border-slate-200/40 pt-2 text-[10px]">
                <span className="text-slate-500">
                  Пошлина:{" "}
                  <span className="font-bold text-slate-700 tabular-nums">
                    {candidate.duty_rate_percent}%
                  </span>
                </span>
                {onApplyCandidate && (
                  <button
                    onClick={() => onApplyCandidate(candidate)}
                    className="text-blue-600 hover:text-blue-800 font-bold transition flex items-center space-x-1 cursor-pointer focus:outline-hidden focus:underline"
                    aria-label={`Применить код ${candidate.hs_code} к расчету`}
                  >
                    <CheckCircle className="h-3.5 w-3.5" />
                    <span>Применить к расчету</span>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Calculation inline */}
      {/* Calculation inline */}
      {msg.calculation && (
        <div className="mt-4 border-t border-slate-100 pt-3 space-y-2">
          <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide block">
            Расчет таможенных платежей:
          </span>
          <div className="bg-slate-50 border border-slate-200/50 rounded-xl p-3.5 text-slate-800 text-xs space-y-1.5">
            <div className="flex justify-between text-[11px]">
              <span className="text-slate-500">Таможенная стоимость:</span>
              <span className="font-bold tabular-nums">
                {msg.calculation.customs_value_kzt?.toLocaleString()} ₸
              </span>
            </div>
            <div className="flex justify-between text-[11px]">
              <span className="text-slate-500">Пошлина:</span>
              <span className="font-bold tabular-nums">
                {msg.calculation.customs_duty_kzt?.toLocaleString()} ₸
              </span>
            </div>
            {msg.calculation.excise_kzt > 0 && (
              <div className="flex justify-between text-[11px]">
                <span className="text-slate-500">Акциз:</span>
                <span className="font-bold tabular-nums">
                  {msg.calculation.excise_kzt?.toLocaleString()} ₸
                </span>
              </div>
            )}
            <div className="flex justify-between text-[11px]">
              <span className="text-slate-500">Импортный НДС:</span>
              <span className="font-bold tabular-nums">
                {msg.calculation.import_vat_kzt?.toLocaleString()} ₸
              </span>
            </div>
            {msg.calculation.recycling_fee_kzt > 0 && (
              <div className="flex justify-between text-[11px]">
                <span className="text-slate-500">Утильсбор:</span>
                <span className="font-bold tabular-nums">
                  {msg.calculation.recycling_fee_kzt?.toLocaleString()} ₸
                </span>
              </div>
            )}
            <div className="flex justify-between border-t border-slate-200/60 pt-2 mt-1.5 font-extrabold text-blue-700 text-sm">
              <span>Итого платежей:</span>
              <span className="tabular-nums">
                {msg.calculation.total_payments_kzt?.toLocaleString()} ₸
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Laws / citations */}
      {msg.laws && msg.laws.length > 0 && (
        <div className="mt-4 border-t border-slate-100 pt-3 space-y-2 text-xs text-slate-800">
          <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wide block">
            Официальные ссылки:
          </span>
          {msg.laws.map((law, lIdx) => (
            <details
              key={lIdx}
              className="bg-blue-50/20 rounded-xl border border-blue-100/30 p-2.5 cursor-pointer group focus-within:ring-2 focus-within:ring-blue-500/20"
            >
              <summary className="font-bold text-blue-800 hover:text-blue-950 hover:underline outline-hidden cursor-pointer flex items-center justify-between">
                <span>{law.document_title}, {law.article_number}</span>
              </summary>
              <p className="mt-1.5 text-slate-600 bg-white p-3 rounded-lg text-[11px] leading-relaxed border-l-2 border-blue-500 select-all italic font-serif shadow-xs text-pretty">
                &ldquo;{law.content_quote}&rdquo;
              </p>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
