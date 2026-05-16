"""
aurora_html.security - hash-based CSP + escape utilities.

Hash-based CSP:
    - Compute SHA-256 of each inline <script> and <style> block at build time.
    - Emit CSP meta tag with 'sha256-{b64hash}' allow-list.
    - Browser refuses to execute ANY script not matching the hash - fundamental
      XSS defense that doesn't rely on perfect input escaping.

Escape utilities:
    - escape(s): HTML entity encode user-controlled strings (channel names).
    - escape_js_embed(data): json.dumps with ensure_ascii=True (protection against
      U+2028/U+2029 Unicode line separators breaking JS string literals).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

# Pre-compiled regex for HTML escape speed (3-5× faster than str.replace chain
# when applied to many short user strings like channel names).
_HTML_ESCAPE_MAP = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
    '{': '&#x7B;',  # defense against str.format() template bomb
    '}': '&#x7D;',
}
_HTML_ESCAPE_RE = re.compile('|'.join(re.escape(k) for k in _HTML_ESCAPE_MAP))


def escape(s: Any) -> str:
    """Safe HTML entity encoding for user-controlled strings.

    Extra protection vs html.escape: also escapes '{' and '}' to defuse
    accidental str.format() template bombs if the escaped value later flows
    through a .format() call.
    """
    if s is None:
        return '-'
    return _HTML_ESCAPE_RE.sub(lambda m: _HTML_ESCAPE_MAP[m.group(0)], str(s))


def escape_js_embed(obj: Any) -> str:
    """Serialize dict/list/value for safe embedding in <script> block.

    ensure_ascii=True escapes ALL non-ASCII (including Cyrillic, emoji,
    U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR) as \\uXXXX. This
    defuses the classic XSS vector where U+2028/U+2029 breaks JS string
    literal parsing.

    v2.1.0 (пилот 2026-05-17 audit H-3): pre-sanitize NaN / Infinity / -Infinity
    в 0. По умолчанию Python json.dumps emits NaN / Infinity keywords - валидный
    JS, но НЕ валидный JSON. ECharts рисует пустые бары / падает с TypeError.
    mroas / spend могут быть NaN если decomposer/optimizer столкнулся с
    channel.contribution=0 или spend=0 (deлeние).
    """
    import math
    def _sanitize(o):
        if isinstance(o, float):
            if math.isnan(o) or math.isinf(o):
                return 0
            return o
        if isinstance(o, dict):
            return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_sanitize(v) for v in o]
        return o
    return json.dumps(_sanitize(obj), ensure_ascii=True, separators=(',', ':'))


def csp_sha256(content: str) -> str:
    """Compute SHA-256 of content, return 'sha256-{base64}' for CSP directive.

    Per CSP3 spec, inline <script> and <style> content hashes use base64-
    encoded SHA-256 (not hex). Normalise to canonical string form first.
    """
    h = hashlib.sha256(content.encode('utf-8')).digest()
    b64 = base64.b64encode(h).decode('ascii')
    return f"'sha256-{b64}'"


def build_csp_meta(script_content: str, style_content: str) -> str:
    """Emit full <meta http-equiv='Content-Security-Policy'> element.

    No 'unsafe-inline' - browser refuses to execute anything not matching
    the hashes. Tight deny policy for network/fetch/connect.
    """
    script_hash = csp_sha256(script_content)
    style_hash = csp_sha256(style_content)
    policy = "; ".join([
        "default-src 'none'",
        "img-src 'self' data: blob:",
        "font-src data:",
        f"style-src {style_hash}",
        f"script-src {script_hash}",
        "connect-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])
    return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
