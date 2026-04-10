"""LanceDB vector store for Brand Hub."""

import lancedb
import pyarrow as pa
from pathlib import Path
from embedder import Embedder
from config import DEFAULT_TOP_K, SIMILARITY_THRESHOLD


class VectorStore:
    def __init__(self, brand_dir: Path):
        self.db_path = brand_dir / "hub"
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_path / "vectors.lance"))
        self.embedder = Embedder()
        self._table = None

    @property
    def table_name(self) -> str:
        return "brand_knowledge"

    @property
    def table(self):
        if self._table is None:
            if self.table_name in self.db.table_names():
                self._table = self.db.open_table(self.table_name)
        return self._table

    def _create_table(self, records: list[dict]):
        self._table = self.db.create_table(
            self.table_name,
            data=records,
            mode="overwrite",
        )

    def add_documents(self, chunks: list[dict], cabinet: str = "docs"):
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        vectors = self.embedder.embed_documents(texts)

        records = [
            {
                "vector": vec,
                "text": chunk["text"],
                "source": chunk.get("source", ""),
                "cabinet": cabinet,
                "chunk_index": chunk.get("chunk_index", 0),
            }
            for vec, chunk in zip(vectors, chunks)
        ]

        if self.table is None:
            self._create_table(records)
        else:
            self.table.add(records)

        return len(records)

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, cabinet: str | None = None) -> list[dict]:
        if self.table is None:
            return []

        query_vec = self.embedder.embed_query(query)
        results = self.table.search(query_vec).limit(top_k).to_list()

        filtered = []
        for r in results:
            score = 1 - r.get("_distance", 1.0)
            if score < SIMILARITY_THRESHOLD:
                continue
            if cabinet and r.get("cabinet") != cabinet:
                continue
            filtered.append({
                "text": r["text"],
                "source": r.get("source", ""),
                "cabinet": r.get("cabinet", ""),
                "score": round(score, 4),
            })

        return filtered

    def count(self) -> int:
        if self.table is None:
            return 0
        return self.table.count_rows()

    def delete_by_source(self, source: str):
        if self.table is not None:
            self.table.delete(f'source = "{source}"')
