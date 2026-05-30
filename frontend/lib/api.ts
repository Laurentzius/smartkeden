// API client — thin fetch wrappers with typed responses.

import type {
  ExchangeRates,
  CalculationRequest,
  CalculationResponse,
  OrchestrateResponse,
  ParseDocumentResponse,
  InvoiceData,
} from "@/types/api";

const API_BASE = ""; // same-origin, Next.js rewrites to backend

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, init);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ── Exchange Rates ──────────────────────────────────────────────────────────
export async function fetchExchangeRates(): Promise<ExchangeRates> {
  return request<ExchangeRates>("/api/rates");
}

// ── Calculator ──────────────────────────────────────────────────────────────
export async function calculateDuties(
  payload: CalculationRequest,
): Promise<CalculationResponse> {
  return request<CalculationResponse>("/api/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── Orchestrator (chat + image classification) ──────────────────────────────
export async function orchestrate(
  text: string,
  sessionId: string,
  history: Array<{ role: string; content: string }>,
  file?: File,
): Promise<OrchestrateResponse> {
  const formData = new FormData();
  formData.append("text", text || "Классифицировать изображение");
  formData.append("session_id", sessionId);
  formData.append("history", JSON.stringify(history));
  if (file) {
    formData.append("file", file);
  }
  return request<OrchestrateResponse>("/api/orchestrate", {
    method: "POST",
    body: formData,
  });
}

// ── Document Generation ─────────────────────────────────────────────────────
export async function downloadExcel(payload: unknown): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/generate-excel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Invoice generation failed");
  return res.blob();
}

export async function downloadWord(payload: unknown): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/generate-word`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Contract generation failed");
  return res.blob();
}

/** Trigger browser download of a Blob. */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

// ── Document Parsing ─────────────────────────────────────────────────────────
export async function parseDocument(
  file: File,
  sessionId: string,
): Promise<ParseDocumentResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);
  return request<ParseDocumentResponse>("/api/workspace/parse-document", {
    method: "POST",
    body: formData,
  });
}

export async function confirmExtraction(
  data: InvoiceData,
  sessionId: string,
): Promise<{ status: string; data: InvoiceData }> {
  const formData = new FormData();
  formData.append("data", JSON.stringify(data));
  formData.append("session_id", sessionId);
  return request("/api/workspace/parse-document/confirm", {
    method: "POST",
    body: formData,
  });
}
