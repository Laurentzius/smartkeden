# System Architecture Map (Cross-Flow Architecture)

This document shows how different business and event flows connect at the system level in **CustomAI Kazakhstan (Кеден Көмекшісі)**.

```mermaid
flowchart LR
    subgraph Orchestrator["Agent Orchestrator"]
        OR_Input[User Message]
        OR_Classify[Intent Classifier]
        OR_RAG --> RAG
        OR_HS --> HS
        OR_Calc --> Calc
        OR_Ingest --> Ingest
    end

    subgraph RAG["Legal RAG Flow"]
        RAG_Query[Formulate legal question]
        RAG_Retrieve[Qdrant Article Chunk Query]
        RAG_Synth[Gemini Article Citation Synthesis]
    end

    subgraph HS["HS Code Classification Flow"]
        HS_Start[Identify Product]
        HS_Vision[Gemini Vision Parse]
        HS_Vector[Qdrant Search hs_code_directory]
        HS_Select[Candidate Selection]
    end

    subgraph Ingest["Document Ingestion Flow"]
        ING_Parse[Local Structure Parsing]
        ING_Dedup[Local Dedup via Granite]
        ING_Embed[Gemini Embedding]
        ING_Store[Upsert to Qdrant]
    end

    subgraph Calc["Customs Calculation Flow"]
        Calc_Fetch[Fetch NBK Exchange Rates]
        Calc_Check[Query TROIS Registry]
        Calc_Math[Deterministic Tax Engine]
        Doc_Gen[Generate Word/Excel documents]
    end

    subgraph VectorDB["Qdrant Vector DB"]
        Q_Legal[(legal_regulations_kz)]
        Q_HS[(hs_code_directory)]
    end

    %% Orchestrator routes
    OR_Classify -- "question_about_law" --> OR_RAG
    OR_Classify -- "product_description" --> OR_HS
    OR_Classify -- "calculation_request" --> OR_Calc
    OR_Classify -- "document_upload" --> OR_Ingest

    %% Cross-Flow Boundaries
    HS_Select -- "selected_hs_code" --> Calc_Math
    RAG -- "article_duty_rate" --> Calc_Math
    HS_Select -- "hs_code_legal_requirements" --> RAG
    Calc_Math -- "calculation_results" --> Doc_Gen

    %% Vector Index Connections
    ING_Store --> Q_Legal
    RAG_Retrieve --> Q_Legal
    HS_Vector --> Q_HS
```

---

## Declared Cross-Flow Boundaries

### 1. HS Code Classification Flow $\rightarrow$ Customs Calculation Flow
* **Trigger Event:** User confirms a 10-digit EAEU HS Code selected by the classifier.
* **Payload:** `{ hs_code: "8543709000", duty_rate_percent: 10.0, is_subject_to_recycling_fee: false }`
* **Consumer:** Calculations Engine (`Calc_Math`) automatically populates the duty rate and recycling parameters for the tariff computation.

### 2. Legal RAG Flow $\rightarrow$ Customs Calculation Flow
* **Trigger Event:** Retrieval of legal technical regulations or anti-dumping duties from official EAEU / RK texts.
* **Payload:** `{ special_duty_rate_percent: 25.5, regulation_id: "EEC-Decision-78" }`
* **Consumer:** Calculation Engine overlays ad-valorem calculations with special or anti-dumping duties where applicable.

### 3. HS Code Classification Flow $\rightarrow$ Legal RAG Flow
* **Trigger Event:** Selected HS Code has active non-tariff regulation alerts (e.g., Phytosanitary certification required).
* **Payload:** `{ hs_code: "1209911000", regulation_category: "phytosanitary" }`
* **Consumer:** Legal RAG service formulates a query to fetch the exact certificate requirement text from RK Technical Regulations.

### 4. Agent Orchestrator $\rightarrow$ Legal RAG Flow
* **Trigger Event:** User message classified as `question_about_law` by Intent Classifier.
* **Payload:** `{ query: "...", top_k: 5 }`
* **Consumer:** `LegalRAGService.query_legal_base()` returns LegalRAGResponse with citations.

### 5. Agent Orchestrator $\rightarrow$ HS Classification Flow
* **Trigger Event:** User message classified as `product_description`.
* **Payload:** `{ description: "...", image_bytes?: File }`
* **Consumer:** `HSCodeClassifier.classify()` returns HSClassificationResponse.

### 6. Agent Orchestrator $\rightarrow$ Customs Calculation Flow
* **Trigger Event:** User message classified as `calculation_request`, or chained from HS classification.
* **Payload:** `{ invoice_price, currency, hs_code, ... }`
* **Consumer:** `CustomsCalculator.calculate()` returns CalculationResponse.

### 7. Document Ingestion Flow $\rightarrow$ Qdrant
* **Trigger Event:** Document uploaded for indexing.
* **Payload:** `{ collection: "legal_regulations_kz", points: [...] }`
* **Consumer:** Qdrant upsert with local in-process dedup.

---

## Implementation Trace & Flow Map

* **Orchestrator:** `backend/app/core/orchestrator/` $\rightarrow$ Flow Document: `flows/features/agent_orchestrator_flow.md`
* **Legal RAG Flow:** `backend/app/core/rag/` $\rightarrow$ Flow Document: `flows/features/semantic_embedding_flow.md`
* **Document Ingestion:** `backend/app/core/rag/indexer.py` $\rightarrow$ Flow Document: `flows/features/blockify_ingestion_flow.md` (Migrated to Local parsing & dedup)
* **HS Code Directory & Classifier:** `backend/app/core/hs_classifier/` $\rightarrow$ Flow Document: `flows/features/hs_classification_flow.md`
* **Customs Calculation:** `backend/app/core/calculation/` $\rightarrow$ Flow Document: `flows/features/customs_calculation_flow.md`
* **Dynamic Profile Extraction (Stateful Accumulator):** `backend/app/core/orchestrator/profile_extractor.py` $\rightarrow$ Flow Document: `flows/features/customs_profile_flow.md`
* **Document Generation:** `backend/app/core/documents/` $\rightarrow$ Flow Document: `flows/features/document_generation_flow.md`
* **KGD Registry & Trademark (TROIS):** `backend/app/services/kgd_registry.py` $\rightarrow$ Flow Document: `flows/features/kgd_registry_flow.md`
* **Vertex AI / Gemini Client:** `backend/app/core/vertex_client.py` $\rightarrow$ Flow Document: `flows/features/langfuse_monitoring_flow.md`
* **Behavior Tests:** `backend/tests/` $\rightarrow$ Covered globally in target traces.
