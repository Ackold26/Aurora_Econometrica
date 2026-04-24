"""
aurora_html.builder — AuroraHTMLBuilder orchestrator.

Assembles the 14-section HTML report by composing:
- outer shell (shell.html template)
- inline assets (CSS, tokens JS, ECharts, WOFF2 fonts as data URIs)
- section renderers (sections.py, 14 functions)
- interactivity JS (interactive.py)
- security metadata (hash-based CSP, escape utilities)
- trust signals (report ID, methodology badges)

Minimal stub in M1; full implementation lands across M2 (narrative),
M3 (interactivity), M4 (themes/polish).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from . import TEMPLATES_DIR

logger = logging.getLogger('econometrica.aurora_html')


class AuroraHTMLBuilder:
    """Build tier-1 Aurora AI interactive HTML report.

    Attributes:
        data: narrative_adapter output (meta/diagnostics/channels/facts).
        initial_theme: 'light' | 'dark' | 'fun'.
        report_id: SHA-256[:12] of (input_data + version + timestamp).
    """

    def __init__(self, data: dict, initial_theme: str = 'light'):
        self.data = data or {}
        self.meta = self.data.get('meta', {}) or {}
        self.diagnostics = self.data.get('diagnostics', {}) or {}
        self.channels = self.data.get('channels') or []
        self.facts = self.data.get('narrative_facts') or {}
        self.initial_theme = initial_theme

        self.client = self.meta.get('client') or 'Client'
        self.project_id = self.meta.get('project_id') or 'PROJECT'
        self.version = self.meta.get('version') or '1.0.12'
        self.report_date = self.meta.get('report_date') or self._fmt_now()
        self.generated_at = datetime.now().isoformat(timespec='seconds')

        self.report_id = self._compute_report_id()

    @staticmethod
    def _fmt_now() -> str:
        months = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        dt = datetime.now()
        return f"{dt.day} {months[dt.month]} {dt.year}"

    def _compute_report_id(self) -> str:
        """SHA-256 hash of (client + project_id + version + channel count +
        diagnostics + timestamp) — provides client-facing traceability. Stable
        per run (not per char of input) so same content → same Report ID.
        """
        fingerprint_input = (
            f"{self.client}|{self.project_id}|{self.version}|"
            f"n_channels={len(self.channels)}|"
            f"diag={sorted(self.diagnostics.items())}|"
            f"ts={self.generated_at}"
        )
        h = hashlib.sha256(fingerprint_input.encode('utf-8')).hexdigest()[:12]
        return f"aurora-mmm-{h}"

    def build(self) -> str:
        """Assemble full HTML string. Minimal stub in M1."""
        # TODO (M2): implement full shell.html + 14 sections + interactivity.
        # For M1, emit a placeholder acknowledging the data flow is wired.
        asset_manifest = self._load_asset_manifest()

        return (
            "<!DOCTYPE html>\n"
            f'<html lang="ru" data-theme="{self.initial_theme}">\n'
            "<head>\n"
            f'<meta charset="UTF-8">\n'
            f'<title>Aurora AI - MMM отчёт</title>\n'
            f'<meta name="generator" content="Aurora AI HTML builder v{__import__("econometrica.aurora_html", fromlist=["__version__"]).__version__}">\n'
            "</head>\n"
            "<body>\n"
            "<!-- M1 skeleton placeholder. Full narrative lands in M2. -->\n"
            f'<h1>Aurora AI</h1>\n'
            f'<p>Client: {self.client}</p>\n'
            f'<p>Report ID: <code>{self.report_id}</code></p>\n'
            f'<p>Channels: {len(self.channels)}</p>\n'
            f'<p>Assets loaded: {len(asset_manifest)} files</p>\n'
            "</body>\n"
            "</html>\n"
        )

    def _load_asset_manifest(self) -> dict[str, int]:
        """List templates dir recursively, return {rel_path: bytes_size}."""
        manifest = {}
        for p in TEMPLATES_DIR.rglob('*'):
            if p.is_file():
                rel = p.relative_to(TEMPLATES_DIR).as_posix()
                manifest[rel] = p.stat().st_size
        return manifest
