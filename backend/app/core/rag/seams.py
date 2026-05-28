import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.core.config import settings

logger = logging.getLogger(__name__)

class EmbeddingModel(ABC):
    """Abstract seam for text embedding generation."""
    @abstractmethod
    def embed_text(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> List[float]:
        pass

class LocalEmbeddingModelAdapter(EmbeddingModel):
    """Local Sentence-Transformers embedding generator adapter."""
    def embed_text(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> List[float]:
        from app.core.local_embeddings import LocalEmbeddingModel
        if LocalEmbeddingModel.is_available():
            return LocalEmbeddingModel.encode(text)
        logger.warning("Local embedding model not available, falling back to mock zero vector")
        return [0.0] * settings.EMBEDDING_DIMENSION

class VertexEmbeddingModelAdapter(EmbeddingModel):
    """Vertex/Gemini AI client embedding generator adapter."""
    def embed_text(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> List[float]:
        from app.core.vertex_client import GeminiVertexClient
        return GeminiVertexClient.get_text_embedding(text, task_type=task_type)

class VectorStorage(ABC):
    """Abstract seam for high-performance vector store (e.g. Qdrant)."""
    @abstractmethod
    def setup_collection(self, collection_name: str, vector_dimension: int, force_recreate: bool = False) -> bool:
        pass

    @abstractmethod
    def retrieve_points(self, collection_name: str, ids: List[str]) -> List[Any]:
        pass

    @abstractmethod
    def upsert_points(self, collection_name: str, points: List[PointStruct]) -> bool:
        pass

    @abstractmethod
    def query_points(self, collection_name: str, query_vector: List[float], limit: int = 3) -> Any:
        pass

    @abstractmethod
    def get_collections(self) -> List[str]:
        pass

    @abstractmethod
    def delete_collection(self, collection_name: str) -> bool:
        pass
    @abstractmethod
    def scroll_points(
        self,
        collection_name: str,
        filter_cond: Optional[Any] = None,
        limit: int = 100,
        offset: Optional[Any] = None,
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> Tuple[List[Any], Optional[Any]]:
        pass
    @abstractmethod
    def delete_points(self, collection_name: str, ids: List[str]) -> bool:
        pass
class QdrantVectorStorageAdapter(VectorStorage):
    """Concrete adapter satisfying VectorStorage seam using QdrantClient."""
    def __init__(self, client_or_url: Optional[Any] = None):
        if client_or_url is not None:
            if isinstance(client_or_url, str):
                self._client = QdrantClient(client_or_url)
            else:
                self._client = client_or_url
        else:
            try:
                self._client = QdrantClient(
                    host=settings.QDRANT_HOST,
                    port=settings.QDRANT_PORT,
                    api_key=settings.QDRANT_API_KEY,
                    timeout=2.0
                )
                self._client.get_collections() # validate connection
            except Exception as e:
                logger.warning(f"Could not connect to Qdrant cluster, falling back to local memory DB: {e}")
                self._client = QdrantClient(":memory:")

    def setup_collection(self, collection_name: str, vector_dimension: int, force_recreate: bool = False) -> bool:
        try:
            collections_resp = self._client.get_collections()
            existing_names = [col.name for col in collections_resp.collections]
            
            if collection_name in existing_names:
                if force_recreate:
                    logger.info(f"Recreating existing Qdrant collection: {collection_name}")
                    self._client.delete_collection(collection_name)
                else:
                    logger.info(f"Qdrant collection '{collection_name}' already exists. Skipping setup.")
                    return True
            
            logger.info(f"Creating Qdrant collection '{collection_name}' (dims={vector_dimension})")
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_dimension,
                    distance=Distance.COSINE
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to setup collection {collection_name}: {e}")
            return False

    def retrieve_points(self, collection_name: str, ids: List[str]) -> List[Any]:
        try:
            return self._client.retrieve(collection_name=collection_name, ids=ids)
        except Exception as e:
            logger.debug(f"Failed to retrieve points in collection {collection_name}: {e}")
            return []

    def upsert_points(self, collection_name: str, points: List[PointStruct]) -> bool:
        try:
            self._client.upsert(collection_name=collection_name, points=points)
            return True
        except Exception as e:
            logger.error(f"Failed to upsert points in collection {collection_name}: {e}")
            return False

    def query_points(self, collection_name: str, query_vector: List[float], limit: int = 3) -> Any:
        return self._client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit
        )

    def get_collections(self) -> List[str]:
        try:
            collections_resp = self._client.get_collections()
            return [col.name for col in collections_resp.collections]
        except Exception:
            return []

    def delete_collection(self, collection_name: str) -> bool:
        try:
            self._client.delete_collection(collection_name)
            return True
        except Exception:
            return False
    def scroll_points(
        self,
        collection_name: str,
        filter_cond: Optional[Any] = None,
        limit: int = 100,
        offset: Optional[Any] = None,
        with_payload: bool = True,
        with_vectors: bool = False,
    ) -> Tuple[List[Any], Optional[Any]]:
        try:
            res, next_page_offset = self._client.scroll(
                collection_name=collection_name,
                scroll_filter=filter_cond,
                limit=limit,
                offset=offset,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )
            return res, next_page_offset
        except Exception as e:
            logger.error(f"Failed to scroll points in collection {collection_name}: {e}")
            return [], None
    def delete_points(self, collection_name: str, ids: List[str]) -> bool:
        try:
            self._client.delete(
                collection_name=collection_name,
                points_selector=ids,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete points in collection {collection_name}: {e}")
            return False