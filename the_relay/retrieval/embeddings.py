"""
Embedding providers and vector cache for dense semantic retrieval.
Supports production SentenceTransformers (all-MiniLM-L6-v2),
cached on-disk vector arrays (.npz), and fast offline deterministic mock providers.
"""
import os
import hashlib
from pathlib import Path
from typing import Optional
from abc import ABC, abstractmethod
import numpy as np

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "embeddings"

class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_query(self, query: str) -> np.ndarray:
        """Embed single query string into normalized 1D vector."""
        pass

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Embed list of document texts into normalized 2D matrix (N, D)."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_version(self) -> str:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

class SentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dimension = 384

    def _load_model(self):
        if self._model is None:
            # Set environment variable to silence symlinks warning on Windows
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()

    def embed_query(self, query: str) -> np.ndarray:
        self._load_model()
        vec = self._model.encode(query, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        self._load_model()
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        return np.asarray(vecs, dtype=np.float32)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "v1"

    @property
    def dimension(self) -> int:
        return self._dimension

class DeterministicMockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Lightweight, completely offline deterministic embedding provider for fast unit tests.
    Computes a normalized unit pseudo-vector using token-level SHA-256 hash buckets.
    """
    def __init__(self, dimension: int = 64, model_name: str = "mock-deterministic-v1"):
        self._dim = dimension
        self._model_name = model_name

    def _hash_text_to_vector(self, text: str) -> np.ndarray:
        words = text.lower().split()
        vec = np.zeros(self._dim, dtype=np.float32)
        if not words:
            vec[0] = 1.0
            return vec

        for w in words:
            h = int(hashlib.sha256(w.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
            vec[idx] += sign

        norm = np.linalg.norm(vec)
        if norm > 1e-6:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec

    def embed_query(self, query: str) -> np.ndarray:
        return self._hash_text_to_vector(query)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._dim), dtype=np.float32)
        matrix = np.stack([self._hash_text_to_vector(t) for t in texts])
        return matrix

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return "mock-v1"

    @property
    def dimension(self) -> int:
        return self._dim

class EmbeddingCache:
    """On-disk cache for chunk embeddings with cryptographic content/model invalidation."""
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_cache_key(
        self, setting_key: str, model_name: str, model_version: str, chunk_ids: list[str], content_hashes: list[str]
    ) -> str:
        hasher = hashlib.sha256()
        hasher.update(f"{setting_key}:{model_name}:{model_version}".encode())
        for cid, chash in zip(chunk_ids, content_hashes):
            hasher.update(f"{cid}:{chash}".encode())
        return hasher.hexdigest()

    def get(self, cache_key: str) -> Optional[np.ndarray]:
        cache_file = self.cache_dir / f"{cache_key}.npz"
        if not cache_file.exists():
            return None
        try:
            with np.load(cache_file) as data:
                return data["embeddings"]
        except Exception:
            return None

    def put(self, cache_key: str, embeddings: np.ndarray, chunk_ids: list[str]):
        cache_file = self.cache_dir / f"{cache_key}.npz"
        np.savez_compressed(
            cache_file,
            embeddings=embeddings.astype(np.float32),
            chunk_ids=np.array(chunk_ids)
        )
