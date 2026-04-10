"""Parser configuration."""

import sys
from pathlib import Path

# Base paths — PyInstaller-compatible
if getattr(sys, 'frozen', False):
    PARSER_ROOT = Path(sys.executable).parent
    BRAND_HUB_ROOT = PARSER_ROOT.parent
else:
    PARSER_ROOT = Path(__file__).parent
    BRAND_HUB_ROOT = PARSER_ROOT.parent
BRANDS_DIR = BRAND_HUB_ROOT / "brands"

# RAG server (for indexing parsed data)
RAG_SERVER_URL = "http://127.0.0.1:7420"

# Parser server
PARSER_PORT = 7421

# SQLite state database
STATE_DB = PARSER_ROOT / "parser_state.db"

# Rate limiting defaults
DEFAULT_REQUEST_DELAY = 1.0  # seconds between requests
MAX_ITEMS_PER_RUN = 1000     # safety limit per platform per run

# Platforms available for MVP
AVAILABLE_PLATFORMS = ["vk", "telegram", "youtube", "wildberries", "rss"]
