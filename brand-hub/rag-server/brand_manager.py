"""Brand management: create, list, update profiles."""

import json
from pathlib import Path
from datetime import datetime
from config import BRANDS_DIR, CONFIG_FILE


def _read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"version": "1.0", "brands": [], "active_brand": None, "parser": {"enabled": False}}


def _write_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def create_brand(brand_id: str, name: str, industry: str = "", description: str = "") -> dict:
    brand_dir = BRANDS_DIR / brand_id
    brand_dir.mkdir(parents=True, exist_ok=True)
    (brand_dir / "hub" / "history" / "analytics").mkdir(parents=True, exist_ok=True)
    (brand_dir / "hub" / "history" / "strategy").mkdir(parents=True, exist_ok=True)
    (brand_dir / "hub" / "history" / "creative").mkdir(parents=True, exist_ok=True)
    (brand_dir / "hub" / "history" / "focus-groups").mkdir(parents=True, exist_ok=True)
    (brand_dir / "hub" / "history" / "copywriter").mkdir(parents=True, exist_ok=True)
    (brand_dir / "hub" / "history" / "art-director").mkdir(parents=True, exist_ok=True)
    (brand_dir / "docs").mkdir(parents=True, exist_ok=True)
    (brand_dir / "raw").mkdir(parents=True, exist_ok=True)

    profile = {
        "brand_id": brand_id,
        "name": name,
        "industry": industry,
        "description": description,
        "tone_of_voice": {},
        "markers": [],
        "stop_words": [],
        "values": [],
        "voice_tone_matrix": {},
        "competitors": [],
        "parser_sources": {},
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    (brand_dir / "hub" / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cfg = _read_config()
    if brand_id not in cfg["brands"]:
        cfg["brands"].append(brand_id)
    if cfg["active_brand"] is None:
        cfg["active_brand"] = brand_id
    _write_config(cfg)

    return profile


def list_brands() -> list[dict]:
    cfg = _read_config()
    result = []
    for bid in cfg["brands"]:
        profile_path = BRANDS_DIR / bid / "hub" / "profile.json"
        if profile_path.exists():
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            docs_count = len(list((BRANDS_DIR / bid / "docs").glob("*")))
            profile["docs_count"] = docs_count
            profile["is_active"] = bid == cfg.get("active_brand")
            result.append(profile)
    return result


def get_brand(brand_id: str) -> dict | None:
    profile_path = BRANDS_DIR / brand_id / "hub" / "profile.json"
    if profile_path.exists():
        return json.loads(profile_path.read_text(encoding="utf-8"))
    return None


def update_brand(brand_id: str, updates: dict) -> dict | None:
    profile_path = BRANDS_DIR / brand_id / "hub" / "profile.json"
    if not profile_path.exists():
        return None
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile.update(updates)
    profile["updated_at"] = datetime.now().isoformat()
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def set_active_brand(brand_id: str):
    cfg = _read_config()
    cfg["active_brand"] = brand_id
    _write_config(cfg)


def get_active_brand() -> str | None:
    return _read_config().get("active_brand")


def get_brand_dir(brand_id: str) -> Path:
    return BRANDS_DIR / brand_id
