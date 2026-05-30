"use client";

import { useState, useRef } from "react";
import type { ChatMessage as ChatMessageType } from "@/types/api";

const INITIAL_MESSAGE: ChatMessageType = {
  role: "assistant",
  text: "Здравствуйте! Я ИИ-консультант «Интеллектуальный Помощник Keden». Я могу подобрать код ТН ВЭД для вашего товара (в том числе по фотографии), проконсультировать по таможенному законодательству РК (RAG по кодексам) и помочь рассчитать таможенные платежи.",
};

export function useChat(sessionId: string) {
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<ChatMessageType[]>([INITIAL_MESSAGE]);
  const [loading, setLoading] = useState(false);

  // File upload state
  const [file, setFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      const f = e.target.files[0];
      setFile(f);
      setFilePreview(URL.createObjectURL(f));
    }
  };

  const clearFile = () => {
    setFile(null);
    setFilePreview(null);
  };

  const appendMessage = (msg: ChatMessageType) => {
    setHistory((prev) => [...prev, msg]);
  };

  return {
    query,
    setQuery,
    history,
    setHistory,
    loading,
    setLoading,
    file,
    filePreview,
    fileInputRef,
    handleFileChange,
    clearFile,
    appendMessage,
  };
}
