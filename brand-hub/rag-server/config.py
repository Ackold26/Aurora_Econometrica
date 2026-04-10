"""Brand Hub RAG Server configuration."""

from pathlib import Path

# Base paths
BRAND_HUB_ROOT = Path(__file__).parent.parent
BRANDS_DIR = BRAND_HUB_ROOT / "brands"
CONFIG_FILE = BRANDS_DIR / "_config.json"

# Embedding model
EMBEDDING_MODEL = "ai-forever/ru-en-RoSBERTa"
EMBEDDING_PREFIXES = {
    "search_query": "search_query: ",
    "search_document": "search_document: ",
    "classification": "classification: ",
    "clustering": "clustering: ",
}

# Chunking
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

# RAG search
DEFAULT_TOP_K = 10
SIMILARITY_THRESHOLD = 0.15

# Server
DEFAULT_PORT = 7420
