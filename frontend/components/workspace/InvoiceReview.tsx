"use client";

import React, { useState, useCallback } from "react";
import type { InvoiceData, InvoiceLine, ProcessingMetadata } from "@/types/api";
import {
  FileText,
  AlertTriangle,
  Check,
  Edit3,
  ArrowRight,
  X,
  Plus,
  Trash2,
} from "lucide-react";

interface InvoiceReviewProps {
  data: InvoiceData;
  metadata: ProcessingMetadata;
  warnings: string[];
  onConfirm: (edited: InvoiceData) => void;
  onCancel: () => void;
  loading?: boolean;
}

const SOURCE_LABELS: Record<string, string> = {
  pdf_text: "PDF (текстовый)",
  pdf_scanned: "PDF (сканированный)",
  xlsx: "Excel",
  image: "Изображение",
};

export function InvoiceReview({
  data: initialData,
  metadata,
  warnings,
  onConfirm,
  onCancel,
  loading,
}: InvoiceReviewProps) {
  const [data, setData] = useState<InvoiceData>(structuredClone(initialData));
  const [isEditing, setIsEditing] = useState(false);

  const updateField = useCallback(
    (field: keyof InvoiceData, value: string) => {
      setData((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const updateLineItem = useCallback(
    (index: number, field: keyof InvoiceLine, value: string | number | boolean) => {
      setData((prev) => {
        const items = [...prev.items];
        items[index] = { ...items[index], [field]: value };
        return { ...prev, items };
      });
    },
    [],
  );

  const addLineItem = useCallback(() => {
    setData((prev) => ({
      ...prev,
      items: [
        ...prev.items,
        {
          description: "",
          quantity: 1,
          unit_price: 0,
          total_price: 0,
        },
      ],
    }));
  }, []);

  const removeLineItem = useCallback((index: number) => {
    setData((prev) => ({
      ...prev,
      items: prev.items.filter((_, i) => i !== index),
    }));
  }, []);

  const formatConfidence = (conf?: number | null): string => {
    if (conf == null) return "—";
    return `${(conf * 100).toFixed(0)}%`;
  };

  return (
    <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-blue-600" />
          <h3 className="text-lg font-semibold text-slate-800">
            Результаты распознавания
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-600">
            {SOURCE_LABELS[metadata.source_type] || metadata.source_type}
          </span>
          {metadata.ocr_confidence != null && (
            <span
              className={`text-xs px-2 py-1 rounded-full ${
                metadata.ocr_confidence >= 0.7
                  ? "bg-green-100 text-green-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              Качество: {formatConfidence(metadata.ocr_confidence)}
            </span>
          )}
        </div>
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <div
              key={i}
              className="flex items-center gap-2 text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2"
            >
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Invoice Header Fields */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <FieldRow
          label="№ инвойса"
          value={data.invoice_number || ""}
          editing={isEditing}
          onChange={(v) => updateField("invoice_number", v)}
        />
        <FieldRow
          label="Дата"
          value={data.invoice_date || ""}
          editing={isEditing}
          onChange={(v) => updateField("invoice_date", v)}
        />
        <FieldRow
          label="Валюта"
          value={data.currency || ""}
          editing={isEditing}
          onChange={(v) => updateField("currency", v)}
        />
        <FieldRow
          label="Продавец"
          value={data.seller || ""}
          editing={isEditing}
          onChange={(v) => updateField("seller", v)}
        />
        <FieldRow
          label="Покупатель"
          value={data.buyer || ""}
          editing={isEditing}
          onChange={(v) => updateField("buyer", v)}
        />
      </div>

      {/* Line Items Table */}
      {data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                <th className="py-2 pr-2">Товар</th>
                <th className="py-2 px-2 w-20">Кол-во</th>
                <th className="py-2 px-2 w-28">Цена за ед.</th>
                <th className="py-2 px-2 w-28">Сумма</th>
                <th className="py-2 px-2 w-16">Вес (кг)</th>
                {isEditing && <th className="py-2 w-8"></th>}
              </tr>
            </thead>
            <tbody>
              {data.items.map((item, i) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-2 pr-2">
                    {isEditing ? (
                      <input
                        type="text"
                        value={item.description}
                        onChange={(e) => updateLineItem(i, "description", e.target.value)}
                        className="w-full text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    ) : (
                      <span className="text-slate-800">{item.description}</span>
                    )}
                    {item.price_estimated && (
                      <span className="ml-1 text-xs text-amber-600" title="Цена не указана">
                        (оценка)
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-2">
                    {isEditing ? (
                      <input
                        type="number"
                        value={item.quantity}
                        onChange={(e) =>
                          updateLineItem(i, "quantity", parseFloat(e.target.value) || 0)
                        }
                        className="w-full text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
                        min={0}
                        step="any"
                      />
                    ) : (
                      <span className="text-slate-700">{item.quantity}</span>
                    )}
                  </td>
                  <td className="py-2 px-2">
                    {isEditing ? (
                      <input
                        type="number"
                        value={item.unit_price}
                        onChange={(e) =>
                          updateLineItem(i, "unit_price", parseFloat(e.target.value) || 0)
                        }
                        className="w-full text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
                        min={0}
                        step="any"
                      />
                    ) : (
                      <span className="text-slate-700">{item.unit_price}</span>
                    )}
                  </td>
                  <td className="py-2 px-2">
                    <span className="text-slate-700 font-medium">{item.total_price}</span>
                  </td>
                  <td className="py-2 px-2">
                    {isEditing ? (
                      <input
                        type="number"
                        value={item.weight_kg ?? ""}
                        onChange={(e) =>
                          updateLineItem(
                            i,
                            "weight_kg",
                            e.target.value ? parseFloat(e.target.value) : (null as unknown as number),
                          )
                        }
                        className="w-full text-sm border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
                        min={0}
                        step="any"
                      />
                    ) : (
                      <span className="text-slate-500">
                        {item.weight_kg != null ? item.weight_kg : "—"}
                      </span>
                    )}
                  </td>
                  {isEditing && (
                    <td className="py-2">
                      <button
                        onClick={() => removeLineItem(i)}
                        className="p-1 text-red-400 hover:text-red-600 transition-colors"
                        title="Удалить строку"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.items.length === 0 && (
        <p className="text-sm text-slate-500 text-center py-4">
          Позиции не найдены. Нажмите &quot;Редактировать&quot;, чтобы добавить вручную.
        </p>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100">
        <button
          onClick={() => setIsEditing(!isEditing)}
          disabled={loading}
          className="flex items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-blue-600 transition-colors disabled:opacity-50"
        >
          {isEditing ? (
            <>
              <Check className="w-4 h-4" />
              Готово
            </>
          ) : (
            <>
              <Edit3 className="w-4 h-4" />
              Редактировать
            </>
          )}
        </button>

        {isEditing && (
          <button
            onClick={addLineItem}
            className="flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Добавить строку
          </button>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={onCancel}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-xl hover:bg-slate-200 transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
            Отмена
          </button>
          <button
            onClick={() => onConfirm(data)}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-xl hover:bg-blue-700 transition-colors disabled:opacity-50 shadow-sm"
          >
            {loading ? (
              <>Загрузка…</>
            ) : (
              <>
                <ArrowRight className="w-4 h-4" />
                Отправить в расчёт
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Inline field row ─────────────────────────────────────────────────────── */

function FieldRow({
  label,
  value,
  editing,
  onChange,
}: {
  label: string;
  value: string;
  editing: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-slate-500">{label}</span>
      {editing ? (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="text-sm border border-slate-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      ) : (
        <span className="text-sm text-slate-800 font-medium">
          {value || "—"}
        </span>
      )}
    </div>
  );
}
