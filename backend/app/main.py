from contextlib import asynccontextmanager
from langfuse import observe
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from app.core.database import engine, Base, SessionLocal
# Ensure models are loaded so Base.metadata knows about them
from app.core import models
from app.core.calculation.engine import CustomsCalculator, CalculationRequest, CalculationResponse
from app.services.exchange_rates import NBKExchangeRatesService
from app.services.kgd_registry import KGDRegistryService
from app.core.rag.service import LegalRAGService, LegalRAGResponse
from app.core.hs_classifier.classifier import HSCodeClassifier, HSClassificationResponse
from app.core.orchestrator import orchestrator_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables and seed initial data."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        KGDRegistryService.seed_initial_brokers(db)
    finally:
        db.close()
    yield

app = FastAPI(
    title="CustomAI Kazakhstan (Кеден Көмекшісі) API",
    description="AI Assistant for Customs Clearance in Kazakhstan",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount sub-routers
app.include_router(orchestrator_router)

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "CustomAI Kazakhstan",
        "version": "1.0.0"
    }

@app.post("/api/calculate", response_model=CalculationResponse, tags=["Calculations"])
async def calculate_payments(req: CalculationRequest):
    """
    Deterministic customs calculation for duty, VAT, excise, and fees.
    """
    return CustomsCalculator.calculate(req)

@app.get("/api/rates", tags=["Exchange Rates"])
async def get_exchange_rates():
    """
    Fetch official daily exchange rates from the National Bank of Kazakhstan (НБРК).
    """
    return NBKExchangeRatesService.fetch_rates()

@app.get("/api/rates/{currency}", tags=["Exchange Rates"])
async def get_specific_rate(currency: str):
    """
    Fetch official exchange rate for a specific currency (e.g., USD, EUR, CNY, RUB).
    """
    try:
        rate = NBKExchangeRatesService.get_rate(currency)
        return {"currency": currency.upper(), "rate_to_kzt": rate}
    except ValueError as e:
        return {"error": str(e)}, 400

class ChatRequest(BaseModel):
    query: str

@app.post("/api/chat", response_model=LegalRAGResponse, tags=["RAG / Legal Chat"])
@observe(name="chat_with_legal_base")
async def chat_with_legal_base(req: ChatRequest):
    """
    Query the indexed Kazakhstan/EAEU customs legislation database.
    Provides expert legal synthesis with direct citations and quotes.
    """
    return await LegalRAGService.query_legal_base(req.query)

@app.post("/api/classify", response_model=HSClassificationResponse, tags=["HS Classification"])
@observe(name="classify_hs_code")
async def classify_hs_code(
    description: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    """
    Identify matching 10-digit EAEU HS Codes (ТН ВЭД) for a product description.
    Supports uploading an optional image file for multimodal vision-aided extraction.
    """
    image_bytes = None
    image_mime_type = "image/jpeg"
    
    if file:
        image_bytes = await file.read()
        image_mime_type = file.content_type or "image/jpeg"
        
    return await HSCodeClassifier.classify(
        description=description,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type
    )
from fastapi.responses import FileResponse
import tempfile
from app.core.documents.generator import DocumentGenerator, CustomsInvoiceSchema, SupplyAgreementSchema
@app.post("/api/generate-excel", tags=["Document Generation"])
async def generate_invoice_excel_api(req: CustomsInvoiceSchema):
    """
    Generate an Excel (.xlsx) commercial invoice from schema data and return it as a downloadable file.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_path = tmp.name
    tmp.close()
    DocumentGenerator.generate_invoice_excel(req, tmp_path)
    return FileResponse(
        tmp_path, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        filename="Commercial_Invoice.xlsx"
    )
@app.post("/api/generate-word", tags=["Document Generation"])
async def generate_contract_word_api(req: SupplyAgreementSchema):
    """
    Generate a Word (.docx) supply agreement contract from schema data and return it as a downloadable file.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    tmp_path = tmp.name
    tmp.close()
    DocumentGenerator.generate_contract_word(req, tmp_path)
    return FileResponse(
        tmp_path, 
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", 
        filename="Supply_Agreement.docx"
    )