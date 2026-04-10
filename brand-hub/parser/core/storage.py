"""Storage engine — run history in SQLite, raw data in JSON files."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .base_parser import NormalizedItem


class RunRecord:
    """A single parser run record."""

    def __init__(self, brand_id: str, platform: str):
        self.brand_id = brand_id
        self.platform = platform
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: Optional[datetime] = None
        self.items_count = 0
        self.errors = 0
        self.status = "running"

    def to_dict(self) -> dict:
        return {
            "brand_id": self.brand_id,
            "platform": self.platform,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "items_count": self.items_count,
            "errors": self.errors,
            "status": self.status,
        }


class Storage:
    """Manages parser run history and raw data files."""

    def __init__(self, db_path: Path, brands_dir: Path):
        self.db_path = db_path
        self.brands_dir = brands_dir
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    items_count INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                )
            """)
            conn.commit()

    def start_run(self, brand_id: str, platform: str) -> int:
        """Record a new parser run, return run ID."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO runs (brand_id, platform, started_at, status) VALUES (?, ?, ?, 'running')",
                (brand_id, platform, now),
            )
            conn.commit()
            return cursor.lastrowid

    def finish_run(self, run_id: int, items_count: int, errors: int, status: str = "success"):
        """Update run record on completion."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, items_count=?, errors=?, status=? WHERE id=?",
                (now, items_count, errors, status, run_id),
            )
            conn.commit()

    def get_history(self, brand_id: str, limit: int = 20) -> List[dict]:
        """Get recent run history for a brand."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs WHERE brand_id=? ORDER BY started_at DESC LIMIT ?",
                (brand_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_status(self) -> List[dict]:
        """Get latest run per brand+platform."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT r.* FROM runs r
                INNER JOIN (
                    SELECT brand_id, platform, MAX(started_at) as max_started
                    FROM runs GROUP BY brand_id, platform
                ) latest ON r.brand_id = latest.brand_id
                    AND r.platform = latest.platform
                    AND r.started_at = latest.max_started
                ORDER BY r.started_at DESC
            """).fetchall()
            return [dict(row) for row in rows]

    def save_raw_data(self, brand_id: str, platform: str, items: List[NormalizedItem]):
        """Save parsed items as JSON in brands/{brand_id}/raw/."""
        if not items:
            return

        raw_dir = self.brands_dir / brand_id / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{platform}-{date_str}.json"
        filepath = raw_dir / filename

        # Append to existing file or create new
        existing = []
        if filepath.exists():
            try:
                existing = json.loads(filepath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                existing = []

        new_data = [item.model_dump(mode="json") for item in items]
        existing.extend(new_data)

        filepath.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
