# SmartKeden — AI Customs Clearance Assistant

AI-powered customs clearance assistant for Kazakhstan / EAEU. Classifies goods by HS codes (ТН ВЭД), calculates duties/VAT/excise fees deterministically, answers legal questions via RAG over EAEU customs law, and generates trade documents (invoices, contracts, specs).

## Problem

Importers and brokers in Kazakhstan manually look up 10-digit HS codes, cross-reference duty rates across multiple legal sources, and calculate payments by hand. This is slow, error-prone, and requires deep knowledge of EAEU customs law. SmartKeden automates the entire pipeline — from product description to final calculation with legal citations.

## Architecture

```
Next.js Client ──HTTP/WebSocket──▶ FastAPI Gateway
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                    ▼
            Orchestrator      HS Classifier       Calculation Engine
            (intent routing)  (Vision + RAG)      (deterministic)
                    │                 │                    │
                    ▼                 ▼                    ▼
            Legal RAG ◀──── Qdrant Vector DB         SQLite/Postgres
            (layout-aware)   (HS codes + laws)        (rates, config)
                    │
                    ▼
            Document Generator (PDF / Excel / Word)
```

**Key design decision:** The calculation engine is 100% deterministic Python — LLMs are never used for math. LLMs handle classification (vision + text → HS code selection) and legal Q&A (RAG with exact article citations to prevent hallucination).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Pydantic v2, SQLAlchemy |
| Frontend | Next.js 16, React 19, Tailwind v4 |
| Vector DB | Qdrant (HS codes + legal documents) |
| Relational DB | PostgreSQL (prod) / SQLite (dev) |
| LLM | Google Gemini (Vertex AI / API key) |
| Embeddings | sentence-transformers (local multilingual-e5) |
| Tracing | Langfuse |
| Documents | WeasyPrint (PDF), openpyxl (Excel), python-docx (Word) |
| Agent Framework | Google ADK 2.0 |
| Infra | Docker Compose (Postgres + Qdrant + Backend + Frontend) |

## Features

- **HS Code Classification** — multimodal pipeline: photo/description → vision extraction → vector retrieval → LLM selection with reasoning
- **Deterministic Calculation** — customs value, duty, excise, VAT, recycling fee, total — all computed via formula, not LLM
- **Legal RAG** — layout-aware chunking of EAEU Customs Code, RK Tax Code, EEC decisions; retrieves exact article quotes
- **Document Generation** — invoices, specifications, supply agreements (PDF/Excel/Word)
- **Admin Panel** — manage HS code directory, laws, rates with full audit logging
- **Orchestrator** — intent classification routes requests to the right subsystem
- **KGD Registry** — broker/logistician lookup, ТРОИС trademark registry, 2GIS locator

## Project Structure

```
smartkeden/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry
│   │   ├── api/                 # Admin endpoints (config, rules, knowledge)
│   │   ├── core/
│   │   │   ├── orchestrator/    # Intent routing + workflow graph
│   │   │   ├── hs_classifier/   # Multimodal HS code selection
│   │   │   ├── calculation/     # Deterministic customs calc engine
│   │   │   ├── rag/             # Layout-aware legal search
│   │   │   ├── documents/       # PDF/Excel/Word generation
│   │   │   ├── llm/             # Gemini client (API key / Vertex / mock)
│   │   │   ├── admin/           # Auth, audit log
│   │   │   └── config.py        # Pydantic settings
│   │   └── services/            # KGD registry, exchange rates, parser
│   └── tests/                   # pytest (admin auth, config audit, RAG, vertex)
├── frontend/                    # Next.js 16 + React 19 + Tailwind v4
├── flows/                       # Flow design docs (auth, RAG, billing, etc.)
├── docker-compose.yml           # Postgres + Qdrant + Backend + Frontend
└── CONTEXT.md                   # Domain model & system architecture
```

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Fill in GOOGLE_API_KEY (and optionally Langfuse keys)

# 2. Start the full stack
docker compose up -d

# 3. Access
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000/docs
# Qdrant:   http://localhost:6333/dashboard
```

Without Docker:
```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

## Tests

```bash
cd backend
pytest                          # full suite
pytest tests/test_admin_auth.py # admin auth flow
pytest -k rag                   # RAG tests only
```
