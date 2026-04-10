"""
AI Agency Test Configuration
"""
import platform
from pathlib import Path

# === Paths ===
PROJECT_ROOT = Path(__file__).parent.parent
CABINETS_ROOT = PROJECT_ROOT / "New_AI_Agency"
CABINET_RS = PROJECT_ROOT / "src-tauri" / "src" / "commands" / "cabinet.rs"

# Exponenta test materials — cross-platform path resolution
if platform.system() == "Windows":
    EXPONENTA_DIR = Path("D:/Рабочий стол/Экспонента")
else:
    EXPONENTA_DIR = Path("/mnt/d/Рабочий стол/Экспонента")
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYNTHETIC_DIR = FIXTURES_DIR / "synthetic"
EXPONENTA_FIXTURES = FIXTURES_DIR / "exponenta"
REPORTS_DIR = Path(__file__).parent / "reports"
CACHE_DIR = REPORTS_DIR / "cache"

# Ensure dirs exist
REPORTS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# === Cabinet definitions ===
# Commands are (slash_command, label, group) — matching cabinet.rs
CABINETS = {
    "creative-director": {
        "commands": [
            "cycle", "comm-audit", "brand-memory", "strategy",
            "creative", "ad-variants", "format-creative", "focus-group",
        ],
        "test_priority": "high",
        "test_materials": "exponenta",
        "smoke_command": "brand-memory",
        "expensive_commands": ["cycle"],
    },
    "communication-strategist": {
        "commands": [
            "strategy", "positioning", "brief", "messages",
            "comm-audit", "focus-group", "quick-diagnostics",
        ],
        "test_priority": "high",
        "test_materials": "exponenta",
        "smoke_command": "positioning",
        "expensive_commands": ["strategy"],
    },
    "lawyer-contracts": {
        "commands": [
            "contract", "contract-batch", "contract-риски",
            "contract-counter-docx", "contract-counter", "contract-сравнить",
            "contract-template", "contract-deadlines", "contract-add-notes",
            "contract-checklist", "contract-агентский", "contract-услуги",
            "contract-подрядчик",
        ],
        "test_priority": "medium",
        "test_materials": "synthetic_legal",
        "smoke_command": "contract-checklist",
        "expensive_commands": ["contract-batch"],
    },
    "lawyer-claims": {
        "commands": [
            "pretension-write", "pretension-reply", "pretension-analyze",
            "pretension-timeline", "nda-draft", "nda-analyze",
            "nda-counter", "nda-counter-docx", "settlement-plan",
        ],
        "test_priority": "medium",
        "test_materials": "synthetic_legal",
        "smoke_command": "nda-analyze",
        "expensive_commands": [],
    },
    "lawyer-advertising": {
        "commands": [
            "qa", "qa-batch", "qa-fix-docx", "qa-fix", "qa-stats",
            "qa-фарма", "qa-fmcg", "qa-финансы", "qa-b2b",
            "qa-манифест", "qa-template",
        ],
        "test_priority": "medium",
        "test_materials": "synthetic_legal",
        "smoke_command": "qa",
        "expensive_commands": ["qa-batch"],
    },
    "media-analyst": {
        "commands": [
            "analytics", "check", "action-title",
            "executive-summary", "bridges", "batch-analytics",
        ],
        "test_priority": "medium",
        "test_materials": "synthetic_media",
        "smoke_command": "action-title",
        "expensive_commands": ["batch-analytics"],
    },
    "communication-analyst": {
        "commands": [
            "media-monitor", "sentiment", "effectiveness",
            "competitors", "key-messages", "crisis-analysis",
        ],
        "test_priority": "medium",
        "test_materials": "synthetic_media",
        "smoke_command": "sentiment",
        "expensive_commands": [],
    },
}

# === Claude CLI settings ===
CLAUDE_TIMEOUT_SECONDS = 600   # 10 minutes per command
CLAUDE_ARGS_BASE = [
    "--print",
    "--output-format", "stream-json",
    "--dangerously-skip-permissions",
    "--verbose",
]

# === Validation thresholds ===
MIN_COMMAND_FILE_BYTES = 50
MIN_CLAUDE_MD_BYTES = 100
MIN_INTEGRATION_OUTPUT_CHARS = 200
MIN_CONFIDENCE_MARKERS = 3      # [HIGH/MEDIUM/LOW] in focus-group output
MIN_CREATIVE_CONCEPTS = 3       # Number of concepts in /creative output
MIN_AD_VARIANTS = 10            # Number of ad variants
