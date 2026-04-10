"""Brand Hub Parser Server — FastAPI application for social data collection."""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from config import PARSER_PORT, BRANDS_DIR, RAG_SERVER_URL, STATE_DB
from core.base_parser import NormalizedItem
from core.deduplicator import Deduplicator
from core.storage import Storage

app = FastAPI(title="Brand Hub Parser", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

storage = Storage(STATE_DB, BRANDS_DIR)
deduplicator = Deduplicator(STATE_DB)

# Track running tasks
_running_tasks: dict[str, str] = {}  # brand_id -> status


def _get_brand_config(brand_id: str) -> dict:
    """Fetch brand config from RAG server."""
    try:
        resp = requests.get(f"{RAG_SERVER_URL}/brands/{brand_id}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


def _get_parser(platform: str, brand_config: dict):
    """Instantiate platform parser."""
    if platform == "vk":
        from platforms.vk import VKParser
        return VKParser(brand_config)
    elif platform == "telegram":
        from platforms.telegram import TelegramParser
        return TelegramParser(brand_config)
    elif platform == "youtube":
        from platforms.youtube import YouTubeParser
        return YouTubeParser(brand_config)
    elif platform == "wildberries":
        from platforms.wildberries import WildberriesParser
        return WildberriesParser(brand_config)
    elif platform == "rss":
        from platforms.rss import RSSParser
        return RSSParser(brand_config)
    return None


def _index_to_rag(brand_id: str, items: list[NormalizedItem]):
    """Send parsed items to RAG server for indexing."""
    for item in items:
        try:
            requests.post(
                f"{RAG_SERVER_URL}/brands/{brand_id}/index-text",
                data={
                    "text": item.text,
                    "source": f"parser-{item.platform}",
                    "cabinet": "raw",
                },
                timeout=10,
            )
        except Exception:
            continue


async def _run_parse(brand_id: str, platform: Optional[str] = None):
    """Execute parsing for a brand (optionally single platform)."""
    brand_config = _get_brand_config(brand_id)
    if not brand_config:
        _running_tasks.pop(brand_id, None)
        return

    brand_config["brand_id"] = brand_id
    sources = brand_config.get("parser_sources", {})
    platforms_to_run = [platform] if platform else [p for p, cfg in sources.items() if cfg.get("enabled")]

    _running_tasks[brand_id] = "running"
    total_items = 0
    total_errors = 0

    for plat in platforms_to_run:
        parser = _get_parser(plat, brand_config)
        if not parser:
            continue

        run_id = storage.start_run(brand_id, plat)
        try:
            items = await parser.fetch_new()
            new_items = deduplicator.filter_new(items)
            deduplicator.mark_seen(new_items)
            storage.save_raw_data(brand_id, plat, new_items)
            _index_to_rag(brand_id, new_items)
            storage.finish_run(run_id, len(new_items), 0, "success")
            total_items += len(new_items)
        except Exception as e:
            storage.finish_run(run_id, 0, 1, f"error: {e}")
            total_errors += 1

    _running_tasks[brand_id] = f"done: {total_items} items, {total_errors} errors"


# ── Endpoints ──


@app.post("/parse/{brand_id}")
async def api_parse_brand(brand_id: str, background_tasks: BackgroundTasks):
    if brand_id in _running_tasks and _running_tasks[brand_id] == "running":
        raise HTTPException(409, f"Parse already running for '{brand_id}'")
    background_tasks.add_task(_run_parse, brand_id)
    return {"status": "started", "brand_id": brand_id}


@app.post("/parse/{brand_id}/{platform}")
async def api_parse_platform(brand_id: str, platform: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_parse, brand_id, platform)
    return {"status": "started", "brand_id": brand_id, "platform": platform}


@app.get("/status")
def api_status():
    db_status = storage.get_all_status()
    return {"running": _running_tasks, "latest_runs": db_status}


@app.get("/status/{brand_id}")
def api_brand_status(brand_id: str):
    return {
        "brand_id": brand_id,
        "running": _running_tasks.get(brand_id),
        "latest_runs": storage.get_all_status(),
    }


@app.get("/history/{brand_id}")
def api_history(brand_id: str, limit: int = 20):
    return storage.get_history(brand_id, limit)


class ParserConfigUpdate(BaseModel):
    parser_sources: dict


@app.post("/config/{brand_id}")
def api_update_config(brand_id: str, data: ParserConfigUpdate):
    try:
        resp = requests.patch(
            f"{RAG_SERVER_URL}/brands/{brand_id}",
            json={"parser_sources": data.parser_sources},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(resp.status_code, resp.text)
    except requests.ConnectionError:
        raise HTTPException(503, "RAG server unavailable")


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "seen_items": deduplicator.count()}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PARSER_PORT
    print(f"PORT:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
