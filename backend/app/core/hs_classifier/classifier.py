import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from app.core.vertex_client import GeminiVertexClient
from app.core.rag.indexer import LegalRAGIndexer
from langfuse import observe
from app.core.config import settings
logger = logging.getLogger(__name__)

class HSCodeCandidate(BaseModel):
    hs_code: str = Field(..., description="10-digit HS Code (ТН ВЭД)")
    product_name_ru: str = Field(..., description="Product category name in Russian")
    duty_rate_percent: float = Field(..., description="Import duty rate percentage")
    excise_rate_percent: float = Field(0.0, description="Excise tax rate percentage")
    is_subject_to_recycling_fee: bool = Field(False, description="Is subject to recycling fee (утильсбор)")
    confidence_score: float = Field(..., description="Confidence score from 0.0 to 1.0")
    reasoning: str = Field(..., description="Explanation of why this code was selected")

class HSClassificationResponse(BaseModel):
    product_description: str = Field(..., description="Cleaned product description")
    candidates: List[HSCodeCandidate] = Field(..., description="Top HS code candidates sorted by confidence")
    qdrant_backed: bool = Field(True, description="Whether candidates were grounded by Qdrant vector search")

class HSCodeClassifier:
    """
    Multimodal HS Code Classifier.
    Implements: Multimodal LLM (Vision) -> Text Description -> Vector Search (Qdrant) -> LLM Selection.
    """
    @staticmethod
    @observe(name="HSCodeClassifier.classify")
    async def classify(
        description: str, 
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = "image/jpeg"
    ) -> HSClassificationResponse:
        
        # 1. If image is provided, run Vision extraction first
        refined_description = description
        if image_bytes:
            logger.info("Extracting product features from image using Gemini Vision")
            vision_prompt = (
                "Analyze this product image for customs classification. "
                "Describe its material, purpose, brand, model, packaging, and any technical features. "
                "Provide a highly descriptive text in Russian."
            )
            try:
                # Use Gemini client to describe the image
                class ImageDescription(BaseModel):
                    extracted_attributes: str
                
                vision_res = GeminiVertexClient.generate_structured_content(
                    prompt=vision_prompt,
                    response_schema=ImageDescription,
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type
                )
                refined_description = f"{description}\n[Extracted from photo]: {vision_res.extracted_attributes}"
            except Exception as e:
                logger.error(f"Image analysis failed, falling back to text only: {e}")
        # 2. Vector search candidate lookup (RAG in Qdrant)
        logger.info(f"Performing vector search in Qdrant for description: {refined_description[:100]}...")
        embedding = GeminiVertexClient.get_text_embedding(
            text=refined_description,
            task_type="RETRIEVAL_QUERY"
        )

        qdrant_candidates = []
        qdrant_backed = False
        try:
            client = LegalRAGIndexer.get_client()
            search_result = client.query_points(
                collection_name=LegalRAGIndexer.HS_CODE_COLLECTION_NAME,
                query=embedding,
                limit=20
            ).points

            if search_result:
                qdrant_backed = True
                for hit in search_result:
                    payload = hit.payload or {}
                    qdrant_candidates.append({
                        "hs_code": payload.get("hs_code", ""),
                        "product_name_ru": payload.get("product_name_ru", ""),
                        "product_name_en": payload.get("product_name_en", ""),
                        "duty_rate_percent": payload.get("duty_rate_percent", 0.0),
                        "excise_rate_percent": payload.get("excise_rate_percent", 0.0),
                        "is_subject_to_recycling_fee": payload.get("is_subject_to_recycling_fee", False),
                        "relevance_score": hit.score,
                        "reasoning_notes": payload.get("reasoning_notes", ""),
                    })
                logger.info(f"Found {len(qdrant_candidates)} candidates from Qdrant")
        except Exception as e:
            logger.warning(f"Qdrant HS code search failed, falling back to pure LLM: {e}")

        # 3. Use Gemini to select and validate candidates
        candidates_context = ""
        if qdrant_candidates:
            candidates_context = "\n\nCandidate HS codes from vector database:\n" + "\n".join(
                f"- {c['hs_code']} ({c['product_name_ru']}) — duty: {c['duty_rate_percent']}%, "
                f"recycling: {'yes' if c['is_subject_to_recycling_fee'] else 'no'}, "
                f"relevance: {c['relevance_score']:.3f}"
                for c in qdrant_candidates
            )

        classifier_prompt = (
            f"As an expert customs declarant in Kazakhstan, analyze the following product description "
            f"and select the top 3-5 most accurate 10-digit HS codes (коды ТН ВЭД ЕАЭС).\n"
            f"Product Description:\n{refined_description}\n"
            f"{candidates_context}\n\n"
            f"Verify each candidate against general EAEU classification rules. "
            f"Use the provided candidate codes as a starting point if available. "
            f"If no candidates were provided from vector search, rely on your training knowledge."
        )

        try:
            result = GeminiVertexClient.generate_structured_content(
                prompt=classifier_prompt,
                response_schema=HSClassificationResponse
            )
            result.product_description = refined_description
            result.qdrant_backed = qdrant_backed
            
            if settings.LANGFUSE_ENABLED:
                try:
                    from langfuse import get_client
                    get_client().update_current_span(
                        metadata={
                            "image_present": bool(image_bytes),
                            "qdrant_backed": qdrant_backed,
                            "candidates_count": len(qdrant_candidates),
                            "refined_description_length": len(refined_description)
                        }
                    )
                except Exception as lf_err:
                    logger.warning(f"Failed to update HS classifier span: {lf_err}")
            
            return result
        except Exception as e:
            logger.error(f"HS Classification failed: {e}")
            # Fallback: return a minimal response so API doesn't hang
            return HSClassificationResponse(
                product_description=refined_description,
                candidates=[
                    HSCodeCandidate(
                        hs_code="0000000000",
                        product_name_ru="Не удалось классифицировать",
                        duty_rate_percent=0.0,
                        confidence_score=0.0,
                        reasoning=f"Ошибка ИИ-классификации: {str(e)[:200]}"
                    )
                ],
                qdrant_backed=qdrant_backed
            )
