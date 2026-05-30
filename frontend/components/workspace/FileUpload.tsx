"use client";

import React, { useCallback, useRef, useState } from "react";
import { Upload, FileWarning, Loader2 } from "lucide-react";

const SUPPORTED_EXTENSIONS = [".pdf", ".xlsx", ".png", ".jpg", ".jpeg"];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  disabled?: boolean;
  loading?: boolean;
}

export function FileUpload({ onFileSelect, disabled, loading }: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((file: File): string | null => {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      return `Неподдерживаемый формат: ${ext}. Поддерживаются PDF, XLSX, PNG, JPG.`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `Файл слишком большой (${(file.size / (1024 * 1024)).toFixed(1)} МБ). Максимальный размер: 10 МБ.`;
    }
    if (file.size === 0) {
      return "Файл пустой.";
    }
    return null;
  }, []);

  const handleFile = useCallback(
    (file: File) => {
      setError(null);
      const err = validateFile(file);
      if (err) {
        setError(err);
        return;
      }
      onFileSelect(file);
    },
    [validateFile, onFileSelect],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled || loading) return;
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile, disabled, loading],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="w-full">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => !disabled && !loading && inputRef.current?.click()}
        className={`
          relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer
          transition-all duration-200
          ${isDragging
            ? "border-blue-400 bg-blue-50 scale-[1.02]"
            : "border-slate-300 bg-slate-50 hover:border-blue-300 hover:bg-blue-50/50"
          }
          ${disabled ? "opacity-50 cursor-not-allowed" : ""}
          ${loading ? "cursor-wait" : ""}
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.xlsx,.png,.jpg,.jpeg"
          className="hidden"
          onChange={handleChange}
          disabled={disabled || loading}
        />

        {loading ? (
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            <p className="text-sm text-slate-600">Обрабатываем документ…</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <Upload className="w-10 h-10 text-slate-400" />
            <div>
              <p className="text-sm font-medium text-slate-700">
                Перетащите файл сюда или{" "}
                <span className="text-blue-600 underline underline-offset-2">
                  выберите
                </span>
              </p>
              <p className="text-xs text-slate-500 mt-1">
                PDF, Excel, JPG, PNG — до 10 МБ
              </p>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-3 flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-2">
          <FileWarning className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
