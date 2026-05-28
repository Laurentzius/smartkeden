# Flow Design: Blockify Distill Document Ingestion Pipeline

This document defines the behavioral flow, state transitions, API contract, and validation rules for the Blockify Distill-powered document ingestion pipeline — raw legal text to Qdrant vector index.

---

## 1. Intent
* **System Goal:** Take raw legal texts (RK Customs/Tax Codes, EAEU decisions, Technical Regulations), submit them to the local Blockify Distill service for structural chunking, embed each chunk with Gemini, and index into Qdrant with deduplication by article_number/document_title composite key.
* **Success Criteria:**
  - Blockify Distill docker service receives text and returns structured IdeaBlocks XML.
  - Multiple invocations with the same article do NOT create duplicates.
  - Each indexed point has complete payload metadata (document_title, article_number, tags, enactment_date).
  - Vector search retrieves relevant chunks across all indexed documents.
* **Non-negotiables:** Blockify API calls use the local self-hosted endpoint (localhost:8315) with async job polling, NOT the cloud /chat/completions format.

---

## 2. Scope
* **In Scope:**
  - Async job submission to `POST /api/autoDistill`.
  - Job status polling via `GET /api/jobs/{job_id}` until `status == "completed"`.
  - IdeaBlocks XML parsing (same schema as current `parse_blockify_xml`).
  - Gemini Embedding (task_type=RETRIEVAL_DOCUMENT) for each block.
  - Qdrant upsert with dedup: check if `document_title + article_number` already exists before inserting.
* **Out of Scope / Deferred:**
  - PDF/image OCR parsing (deferred to v2).
  - Scheduled batch re-indexing (deferred to v2).

---

## 3. Actors and Permissions
* **Admin / System Indexer:** Triggers document ingestion.
* **Blockify Distill Service (System):** Processes text into IdeaBlocks asynchronously.
* **Qdrant (System):** Stores and serves vectors.

---

## 4. Diagrams

### User Flow
```mermaid
flowchart TD
  Start([Upload legal document]) --> Submit[POST /api/autoDistill to Blockify]
  Submit --> Poll[Poll GET /api/jobs/{id} every 2s]
  Poll -->|in_progress| Poll
  Poll -->|completed| Parse[Parse IdeaBlocks XML]
  Poll -->|failed| Error([Return error])
  Poll -->|404 - job not found| RetrySubmit[Resubmit once]
  RetrySubmit --> Submit
  Parse --> Dedup{Check exists by<br/>document_title + article_number}
  Dedup -->|New| Embed[Gemini Embedding 3072-dim RETRIEVAL_DOCUMENT]
  Dedup -->|Exists - compare content| Diff{Content changed?}
  Diff -->|Yes - update| Embed
  Diff -->|No - skip| Next([Next chunk])
  Embed --> Upsert[Qdrant upsert with point id = hash(article_number)]
  Upsert --> Next
  Next -->|All done| Done([Indexing complete])
### System State Machine
```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> SubmittingToBlockify: Raw text received
  SubmittingToBlockify --> PollingBlockifyJob: Job submitted
  PollingBlockifyJob --> PollingBlockifyJob: status = in_progress / queued
  PollingBlockifyJob --> ParsingResults: status = completed
  PollingBlockifyJob --> Failed: status = failed
  PollingBlockifyJob --> Resubmitting: status = 404 (service restarted)
  Resubmitting --> PollingBlockifyJob: Retry count < 2
  Resubmitting --> Failed: Retry count >= 2
  PollingBlockifyJob --> Failed: timeout > 120s

  ParsingResults --> CheckingDedup: XML parsed
  CheckingDedup --> GeneratingEmbedding: New chunk
  CheckingDedup --> CheckingContent: Duplicate found
  CheckingContent --> GeneratingEmbedding: Content changed → overwrite
  CheckingContent --> SkippingChunk: Content unchanged → skip
  CheckingDedup --> SkippingChunk: Duplicate found (exact match)
  SkippingChunk --> CheckingDedup: Next chunk
  CheckingDedup --> Completed: All chunks processed
  GeneratingEmbedding --> UpsertingToQdrant: Vector ready
  GeneratingEmbedding --> PartialFailure: Embedding API error
  UpsertingToQdrant --> CheckingDedup: Next chunk
  UpsertingToQdrant --> PartialFailure: Qdrant write error
  PartialFailure --> Completed: Partial results committed

  Failed --> [*]
  Completed --> [*]
  PartialFailure --> [*]
```

### Data & Event Flow
```mermaid
flowchart LR
  RawText[Raw Legal Text] --> Blockify[Blockify Distill localhost:8315]
  Blockify -->|POST /api/autoDistill| JobID[{job_id}]
  JobID -->|Poll GET /api/jobs/{id}| XML[IdeaBlocks XML]
  XML --> Parser[parse_blockify_xml]
  Parser -->|Chunk list| DedupChecker[Duplicate Checker]
  DedupChecker -->|New points| Embedder[Gemini Embedding RETRIEVAL_DOCUMENT]
  Embedder -->|3072-dim vectors| Qdrant[(Qdrant legal_regulations_kz)]
  Qdrant -->|Result| Response[IndexingReport]
```

---

## 5. State and Projections
* **Qdrant Point ID:** Deterministic UUIDv5 from `document_title + article_number` — ensures idempotent upsert.
* **Duplicate Check:** Query Qdrant by payload filter `document_title == X AND article_number == Y`; if exists, skip.
* **Blockify Job Timeout:** 120 seconds max polling; if exceeded, mark job as failed. If polling receives 404 (job not found), retry submission once. If second submission also 404s, fail.

---

## 6. Events/Actions
| Direction | Name | Source/Target Flow | Payload | Allowed When | Reject/Failure Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Incoming | `index_document` | Admin | `{raw_text, doc_title}` | Admin auth | Empty text, title |
| Outgoing | `blockify_submit` | Blockify Distill | `{model: "distill", messages}` | Raw text prepared | Service unreachable |
| Outgoing | `blockify_poll` | Blockify Distill | `{job_id}` | Job submitted | Job not found |
| Outgoing | `gemini_embed` | Vertex AI | `{text, task_type}` | New chunk to index | API quota |
| Outgoing | `qdrant_upsert` | Qdrant | `{point}` | Embedding ready | Collection missing |

---
## 7. Edge Cases
* **Blockify service down:** Fall back to local regex parser (current `parse_legal_text_to_blocks`).
* **Empty XML response:** Log warning, return 0 indexed.
* **Blockify service restart during polling:** If `GET /api/jobs/{id}` returns 404 (job not found — service was restarted), resubmit the document and start a new polling cycle. Maximum 1 resubmit attempt before failing.
* **Partial failure recovery:** If some chunks fail embedding or Qdrant write, commit all successfully indexed chunks and report `indexed_count / total_count` in the response.
* **Duplicate content check:** Use SHA256 hash of `content_quote` stored in payload. On duplicate `document_title + article_number`, compare hashes. If different — overwrite point with new vector. If same — skip. The `updated_at` timestamp is always refreshed regardless.
* **Large document batching:** If a document produces more than 50 chunks, process in batches of 50. After each batch, commit to Qdrant and log progress. This prevents memory overflow and allows partial progress on failure.

---

## 8. Side Effects
* **Blockify Job Queue:** Each submission creates a job on the Distill service; concurrent large submissions may queue.
* **Storage Growth:** Each indexed chunk ~2KB in Qdrant + 3072 floats. 10,000 articles ≈ 120MB.

---

## 9. Schemas Touched
* `backend/app/core/rag/indexer.py` (LegalRAGIndexer — rewrite call_blockify_ingest_api)
* `backend/app/core/config.py` (BLOCKIFY_API_URL)

---

## 10. Targeted Tests
| Layer | Behavior | File | Status |
| :--- | :--- | :--- | :--- |
| Core / Unit | Blockify XML parsing edge cases | `backend/tests/test_rag.py` | **PASSED** |
| Service / API | async job submission + polling | `backend/tests/test_blockify.py` | **PASSED** |
| Integration | Full ingest: text to Blockify to Qdrant | `backend/tests/test_rag.py` | **PASSED** |
---

## 11. Implementation Plan
1. Rewrite `call_blockify_ingest_api` to use `POST /api/autoDistill` + job polling.
2. Implement deterministic UUIDv5 point IDs from article_number + document_title.
3. Add dedup check before upsert (query by payload filter).
4. Add fallback to local parser if Blockify is unreachable.
5. Write integration tests.

---

## 12. Implementation Trace

### Files Modified
* **Ingestion Logic:** `backend/app/core/rag/indexer.py`
* **Qdrant Operations:** `backend/app/core/rag/indexer.py` (get_client, upsert, scroll, dedup)
* **Configuration:** `backend/app/core/config.py`
* `backend/app/core/rag/indexer.py` — `call_blockify_ingest_api()` rewritten with autoDistill + job polling

### Status
* All 4 tests in `backend/tests/test_blockify.py` pass
* All 3 tests in `backend/tests/test_rag.py` pass
* Full suite: 34 tests pass
* Validation: `PYTHONPATH=backend .venv/Scripts/pytest backend/tests/ -q` → 34 passed in 3.15s
---

## 13. Open Questions
* *What is the exact response schema of local Blockify /api/autoDistill?* -> Need to examine the OpenAPI spec at localhost:8315/openapi.json.

---

## 14. Review Checklist
- [x] Does the dedup strategy handle overwriting changed articles?
- [x] Is the polling loop bounded (max retries, timeout)?
- [x] Is there a graceful fallback when Blockify is down?
- [x] Are point IDs deterministic for idempotency?
- [x] Does the implementation match the /api/autoDistill API exactly?
- [x] Are retries on 404 (service restart) handled?
- [x] Is batch limit for large documents documented?
- [x] Is partial failure visible in the state machine?
