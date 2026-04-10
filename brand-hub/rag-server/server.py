"""Brand Hub RAG Server — FastAPI application."""

import sys
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from config import DEFAULT_PORT, BRANDS_DIR
from brand_manager import (
    create_brand, list_brands, get_brand, update_brand,
    set_active_brand, get_active_brand, get_brand_dir,
)
from vector_store import VectorStore
from chunker import process_file, chunk_text

app = FastAPI(title="Brand Hub RAG Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Cache vector stores per brand
_stores: dict[str, VectorStore] = {}


def _get_store(brand_id: str) -> VectorStore:
    if brand_id not in _stores:
        brand_dir = get_brand_dir(brand_id)
        if not brand_dir.exists():
            raise HTTPException(404, f"Brand '{brand_id}' not found")
        _stores[brand_id] = VectorStore(brand_dir)
    return _stores[brand_id]


# ── Brand Management ──────────────────────────────────────


class BrandCreate(BaseModel):
    brand_id: str
    name: str
    industry: str = ""
    description: str = ""


class BrandUpdate(BaseModel):
    tone_of_voice: dict | None = None
    markers: list[str] | None = None
    stop_words: list[str] | None = None
    values: list[str] | None = None
    voice_tone_matrix: dict | None = None
    competitors: list[dict] | None = None
    parser_sources: dict | None = None
    description: str | None = None


@app.post("/brands")
def api_create_brand(data: BrandCreate):
    return create_brand(data.brand_id, data.name, data.industry, data.description)


@app.get("/brands")
def api_list_brands():
    return list_brands()


@app.get("/brands/{brand_id}")
def api_get_brand(brand_id: str):
    brand = get_brand(brand_id)
    if not brand:
        raise HTTPException(404, f"Brand '{brand_id}' not found")
    return brand


@app.patch("/brands/{brand_id}")
def api_update_brand(brand_id: str, data: BrandUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    result = update_brand(brand_id, updates)
    if not result:
        raise HTTPException(404, f"Brand '{brand_id}' not found")
    return result


@app.delete("/brands/{brand_id}")
def api_delete_brand(brand_id: str):
    brand_dir = get_brand_dir(brand_id)
    if not brand_dir.exists():
        raise HTTPException(404, f"Brand '{brand_id}' not found")
    # Remove from cache
    _stores.pop(brand_id, None)
    # Remove directory
    shutil.rmtree(brand_dir)
    # Remove from config
    from brand_manager import _read_config, _write_config
    cfg = _read_config()
    cfg["brands"] = [b for b in cfg.get("brands", []) if b != brand_id]
    if cfg.get("active_brand") == brand_id:
        cfg["active_brand"] = cfg["brands"][0] if cfg["brands"] else None
    _write_config(cfg)
    return {"deleted": brand_id}


@app.post("/brands/{brand_id}/activate")
def api_set_active(brand_id: str):
    set_active_brand(brand_id)
    return {"active_brand": brand_id}


@app.get("/active-brand")
def api_get_active():
    return {"active_brand": get_active_brand()}


# ── Document Upload & Indexing ────────────────────────────


@app.post("/brands/{brand_id}/upload")
async def api_upload_doc(brand_id: str, file: UploadFile = File(...)):
    brand_dir = get_brand_dir(brand_id)
    if not brand_dir.exists():
        raise HTTPException(404, f"Brand '{brand_id}' not found")

    docs_dir = brand_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    dest = docs_dir / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    chunks = process_file(dest)
    store = _get_store(brand_id)
    count = store.add_documents(chunks, cabinet="docs")

    return {"filename": file.filename, "chunks_indexed": count, "total_vectors": store.count()}


@app.post("/brands/{brand_id}/index-text")
def api_index_text(brand_id: str, text: str = Form(...), source: str = Form("manual"), cabinet: str = Form("docs")):
    chunks = chunk_text(text, source=source)
    store = _get_store(brand_id)
    count = store.add_documents(chunks, cabinet=cabinet)
    return {"chunks_indexed": count, "total_vectors": store.count()}


@app.post("/brands/{brand_id}/reindex")
def api_reindex(brand_id: str):
    brand_dir = get_brand_dir(brand_id)
    if not brand_dir.exists():
        raise HTTPException(404, f"Brand '{brand_id}' not found")

    docs_dir = brand_dir / "docs"
    if not docs_dir.exists():
        return {"files_processed": 0, "total_chunks": 0}
    store = _get_store(brand_id)
    total = 0
    for file_path in docs_dir.iterdir():
        if file_path.is_file():
            chunks = process_file(file_path)
            total += store.add_documents(chunks, cabinet="docs")

    return {"files_processed": len(list(docs_dir.iterdir())), "total_chunks": total}


# ── RAG Search ────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    cabinet: str | None = None


@app.post("/brands/{brand_id}/search")
def api_search(brand_id: str, req: SearchRequest):
    store = _get_store(brand_id)
    results = store.search(req.query, top_k=req.top_k, cabinet=req.cabinet)
    return {"brand_id": brand_id, "query": req.query, "results": results, "count": len(results)}


# ── Stats ─────────────────────────────────────────────────


@app.get("/brands/{brand_id}/stats")
def api_stats(brand_id: str):
    store = _get_store(brand_id)
    brand_dir = get_brand_dir(brand_id)
    docs_count = len(list((brand_dir / "docs").glob("*"))) if (brand_dir / "docs").exists() else 0
    raw_count = len(list((brand_dir / "raw").glob("*"))) if (brand_dir / "raw").exists() else 0
    return {
        "brand_id": brand_id,
        "vectors": store.count(),
        "documents": docs_count,
        "raw_data_files": raw_count,
    }


# ── Health ────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Entry Point ───────────────────────────────────────────


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    print(f"PORT:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
