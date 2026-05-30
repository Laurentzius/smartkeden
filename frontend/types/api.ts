// Types mirroring FastAPI backend Pydantic models.
// Keep in sync with backend/app/core/models.py and orchestrator models.

// ── Exchange Rates ──────────────────────────────────────────────────────────
export interface ExchangeRates {
  [currency: string]: number;
}

// ── Calculator ──────────────────────────────────────────────────────────────
export interface CalculationRequest {
  invoice_price: number;
  currency: string;
  exchange_rate: number;
  transport_to_border: number;
  duty_rate_percent: number;
  excise_rate_percent: number;
  excise_specific_rate?: number;
  excise_units_count?: number;
  is_subject_to_recycling_fee: boolean;
}

export interface CalculationResponse {
  customs_value_kzt: number;
  customs_fee_kzt: number;
  customs_duty_kzt: number;
  excise_kzt: number;
  import_vat_kzt: number;
  recycling_fee_kzt: number;
  total_payments_kzt: number;
  trois_warning?: string;
}

// ── HS Classification ───────────────────────────────────────────────────────
export interface HSCodeCandidate {
  hs_code: string;
  product_name_ru: string;
  product_name_en?: string;
  duty_rate_percent: number;
  excise_rate_percent: number;
  is_subject_to_recycling_fee: boolean;
  confidence_score: number;
  reasoning: string;
  section?: string;
  group?: number;
}

export interface HSClassificationResponse {
  candidates: HSCodeCandidate[];
}

// ── Legal RAG ───────────────────────────────────────────────────────────────
export interface LegalChunk {
  document_title: string;
  article_number: string;
  content_quote: string;
  tags?: string[];
  keywords?: string;
}

export interface LegalRAGResponse {
  chunks: LegalChunk[];
}

// ── Orchestrator ────────────────────────────────────────────────────────────
export interface OrchestrateRequest {
  text: string;
  session_id?: string;
  history?: Array<{ role: string; content: string }>;
}

export interface OrchestrateResponse {
  intent: string;
  message: string;
  pipeline_results?: {
    supporting_laws?: LegalChunk[];
    candidates?: HSCodeCandidate[];
    calculation_response?: CalculationResponse;
  };
  chain_warning?: string;
}

// ── Chat Message (client-side) ──────────────────────────────────────────────
export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  laws?: LegalChunk[];
  candidates?: HSCodeCandidate[];
  calculation?: CalculationResponse;
  chain_warning?: string;
  filePreview?: string;
  fileName?: string;
}

// ── Document Generation ─────────────────────────────────────────────────────
export interface InvoiceGenerateRequest {
  seller_name: string;
  buyer_name: string;
  incoterms: string;
  items: Array<{
    name: string;
    hs_code: string;
    qty: number;
    unit: string;
    price: number;
  }>;
}

export interface ContractGenerateRequest {
  contract_no: string;
  contract_date: string;
  seller_name: string;
  buyer_name: string;
  incoterms: string;
}

// ── Document Parsing ─────────────────────────────────────────────────────────
export interface InvoiceLine {
  description: string;
  quantity: number;
  unit_price: number;
  total_price: number;
  weight_kg?: number | null;
  hs_code_hint?: string | null;
  price_estimated?: boolean;
}

export interface InvoiceData {
  invoice_number?: string | null;
  invoice_date?: string | null;
  seller?: string | null;
  buyer?: string | null;
  currency?: string | null;
  items: InvoiceLine[];
}

export interface ProcessingMetadata {
  source_type: string;
  ocr_confidence?: number | null;
  parsed_at: string;
  original_filename: string;
}

export interface ParseDocumentResponse {
  data: InvoiceData;
  metadata: ProcessingMetadata;
  warnings: string[];
}
