"use client";

import React from "react";
import { MessageSquare, Paperclip } from "lucide-react";
import type { ChatMessage as ChatMessageType, HSCodeCandidate } from "@/types/api";
import { ChatMessage } from "./ChatMessage";

interface ChatWorkspaceProps {
  sessionId: string;
  history: ChatMessageType[];
  loading: boolean;
  query: string;
  onQueryChange: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  filePreview: string | null;
  file: File | null;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onClearFile: () => void;
  onApplyCandidate?: (candidate: HSCodeCandidate) => void;
}

export function ChatWorkspace({
  sessionId,
  history,
  loading,
  query,
  onQueryChange,
  onSubmit,
  filePreview,
  file,
  fileInputRef,
  onFileChange,
  onClearFile,
  onApplyCandidate,
}: ChatWorkspaceProps) {
  return (
    <section className="lg:col-span-7 flex flex-col h-[650px] bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-slate-50 border-b border-slate-100 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-2.5">
          <div className="bg-teal-500/10 p-2 rounded-lg text-teal-600">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-800 text-base">
              «Интеллектуальный Помощник Keden»
            </h3>
            <p className="text-xs text-slate-500">
              Мультимодальный подбор кодов ТН ВЭД, правовой RAG и расчеты
            </p>
          </div>
        </div>
        <div className="text-[10px] bg-slate-200/60 text-slate-600 px-2 py-1 rounded font-mono">
          SESS: {sessionId.substring(0, 8)}...
        </div>
      </div>

      {/* Chat Feed */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4 text-sm bg-slate-50/50">
        {history.map((msg, idx) => (
          <ChatMessage
            key={idx}
            msg={msg}
            onApplyCandidate={onApplyCandidate}
          />
        ))}

        {/* Loading state */}
        {loading && (
          <div className="bg-white border border-slate-100 rounded-2xl p-4 text-slate-500 text-xs self-start flex items-center space-x-2 shadow-sm max-w-[85%] rounded-tl-none">
            <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce" />
            <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce [animation-delay:0.2s]" />
            <span className="h-2 w-2 bg-teal-500 rounded-full animate-bounce [animation-delay:0.4s]" />
            <span>ИИ Keden анализирует ваш запрос...</span>
          </div>
        )}
      </div>

      {/* Chat Form */}
      <div className="p-4 border-t border-slate-100 bg-white flex flex-col space-y-2">
        {/* File preview strip */}
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
                onClick={onClearFile}
                className="absolute -top-1.5 -right-1.5 bg-red-500 text-white rounded-full h-4 w-4 flex items-center justify-center text-[10px] font-bold hover:bg-red-600 cursor-pointer"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-slate-700 truncate">
                {file?.name}
              </p>
              <p className="text-[10px] text-slate-400 font-mono">
                {(file?.size ? file.size / 1024 : 0).toFixed(1)} KB
              </p>
            </div>
          </div>
        )}

        <form onSubmit={onSubmit} className="flex items-center space-x-2">
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
            onChange={onFileChange}
            className="hidden"
          />
          <input
            type="text"
            required={!file}
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Спросите Keden о ТН ВЭД, законодательстве или прикрепите фото..."
            className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-slate-900 text-sm focus:border-teal-500 focus:outline-none placeholder-slate-400"
          />
          <button
            type="submit"
            disabled={loading || (!query.trim() && !file)}
            className="bg-teal-600 hover:bg-teal-700 text-white font-bold px-5 py-2.5 rounded-lg text-sm transition duration-150 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed shrink-0 cursor-pointer"
          >
            Отправить
          </button>
        </form>
      </div>
    </section>
  );
}
