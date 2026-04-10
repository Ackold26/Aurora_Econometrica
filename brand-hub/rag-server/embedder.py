"""Embedding engine using ru-en-RoSBERTa."""

from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL, EMBEDDING_PREFIXES


class Embedder:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
        return cls._instance

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [EMBEDDING_PREFIXES["search_document"] + t for t in texts]
        return self.model.encode(prefixed, normalize_embeddings=True).tolist()

    def embed_query(self, query: str) -> list[float]:
        prefixed = EMBEDDING_PREFIXES["search_query"] + query
        return self.model.encode([prefixed], normalize_embeddings=True)[0].tolist()

    def embed_for_classification(self, texts: list[str]) -> list[list[float]]:
        prefixed = [EMBEDDING_PREFIXES["classification"] + t for t in texts]
        return self.model.encode(prefixed, normalize_embeddings=True).tolist()

    @property
    def dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()
