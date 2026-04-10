"""Deduplication engine — tracks seen items in SQLite."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .base_parser import NormalizedItem


class Deduplicator:
    """Tracks seen items to prevent duplicate indexing."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_items (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    collected_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def filter_new(self, items: List[NormalizedItem]) -> List[NormalizedItem]:
        """Return only items not previously seen."""
        if not items:
            return []

        with sqlite3.connect(self.db_path) as conn:
            existing = set()
            # Check in batches of 500
            ids = [item.id for item in items]
            for i in range(0, len(ids), 500):
                batch = ids[i:i + 500]
                placeholders = ",".join(["?"] * len(batch))
                rows = conn.execute(
                    f"SELECT id FROM seen_items WHERE id IN ({placeholders})",
                    batch,
                ).fetchall()
                existing.update(row[0] for row in rows)

        return [item for item in items if item.id not in existing]

    def mark_seen(self, items: List[NormalizedItem]):
        """Mark items as seen."""
        if not items:
            return
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO seen_items (id, platform, collected_at) VALUES (?, ?, ?)",
                [(item.id, item.platform, now) for item in items],
            )
            conn.commit()

    def count(self, platform: str = None) -> int:
        """Count seen items, optionally filtered by platform."""
        with sqlite3.connect(self.db_path) as conn:
            if platform:
                row = conn.execute(
                    "SELECT COUNT(*) FROM seen_items WHERE platform = ?", (platform,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM seen_items").fetchone()
            return row[0] if row else 0
