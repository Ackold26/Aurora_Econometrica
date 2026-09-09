"""
Brand verification for aurora_html tier-1 (M5).

Asserts 25+ brand + security + structural invariants on a fully rendered
HTML output using realistic test data.

Run:
    cd sidecar && python ../tools/verify_aurora_html_brand.py

Exit 0 on success, 1 on any assertion failure.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "sidecar"
sys.path.insert(0, str(SIDECAR))
sys.path.insert(0, str(SIDECAR / "econometrica"))


def _expected_confidentiality() -> str:
    """Метка конфиденциальности — из той же таблицы строк, что и у сборщика отчёта.

    Сборщик берёт её из strings["brand"]["confidentiality"] (aurora_html/builder.py),
    поэтому и проверка обязана брать оттуда же. Жёстко вписанное сюда значение
    разъезжается с таблицей при первом же переводе и красит корректный отчёт:
    ровно это случилось 09.09.2026, когда строку перевели в «КОНФИДЕНЦИАЛЬНО».
    """
    import json
    p = SIDECAR / "econometrica" / "aurora_html" / "strings_ru.json"
    return json.loads(p.read_text(encoding="utf-8"))["brand"]["confidentiality"]


def _check(label: str, cond: bool, detail: str = "") -> bool:
    tag = "[OK]  " if cond else "[FAIL]"
    line = f"{tag} {label}"
    if detail:
        line += f" - {detail}"
    print(line)
    return cond


def _build_sample_html() -> str:
    from engines.html_export import build_html
    model = {
        'diagnostics': {
            'mqs': {'score': 87, 'tier_label': 'GOOD'},
            'metrics': {'r_squared': 0.872, 'mape_pct': 8.3, 'r_hat_max': 1.008, 'ess_min': 1247},
        },
        'channel_params': {
            'TV': {'beta': 0.42, 'alpha': 1.5, 'gamma': 0.8, 'adstock': 0.6},
            'Digital': {'beta': 0.28, 'alpha': 1.8, 'gamma': 0.5, 'adstock': 0.3},
        },
        'normalization': {'y_mean': 100e6, 'y_std': 25e6,
                          'media_means': {'TV': 20e6, 'Digital': 10e6}},
    }
    decompose = {
        'channels': [
            {'name': 'Digital', 'spend': 65e6, 'contribution': 124e6, 'roi': 1.9},
            {'name': 'TV',      'spend': 120e6, 'contribution': 180e6, 'roi': 1.5},
        ],
        'waterfall': {'labels': ['Base', 'Digital', 'TV'], 'values': [500, 124, 180]},
        'time_series': {'dates': ['W01', 'W02', 'W03'], 'baseline': [38, 40, 42],
                        'channels': {'Digital': [8, 9, 10], 'TV': [12, 14, 16]}},
    }
    optimize = {
        'channels': [
            {'name': 'Digital', 'current_spend': 65e6,  'optimal_spend': 110e6},
            {'name': 'TV',      'current_spend': 120e6, 'optimal_spend': 90e6},
        ],
        'expected_lift_pct': 12.5,
    }
    out = 'tools/_brand_verify.html'
    Path(out).parent.mkdir(exist_ok=True)
    build_html(model, decompose, optimize, out,
               scenarios=[], project_id='Acme-Corp-2026', initial_theme='light')
    html = Path(out).read_text(encoding='utf-8')
    try:
        os.remove(out)
    except OSError:
        pass
    return html


def main() -> int:
    # Без аргумента — собрать образец сборщиком отчёта на выдуманных данных
    # (проверяет сам сборщик). С аргументом — проверить ГОТОВЫЙ документ, который
    # уходит клиенту.
    #
    # 09.09.2026: до этой правки второй режим отсутствовал вовсе, и «34/34» означало
    # «образец чист», а не «клиентский отчёт чист». На живой выгрузке того же дня
    # лежало шесть длинных тире — то есть зелёный вердикт и настоящее состояние
    # документа относились к разным файлам.
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        if not src.is_file():
            print(f"Файл не найден: {src}")
            return 2
        html = src.read_text(encoding='utf-8')
        print(f"Проверяется готовый документ: {src}  ({len(html)/1024:.0f} КБ)")
    else:
        html = _build_sample_html()
        print("Проверяется образец, собранный сборщиком отчёта "
              "(готовый документ — передать путь аргументом)")
    results = []

    # ─── Brand identity ────────────────────────────────────────
    results.append(_check("Aurora AI wordmark present", "Aurora AI" in html))
    results.append(_check("No 'Econometrica' substring in output",
                          "Econometrica" not in html))
    results.append(_check("Sacred lime #CCFF00 in CSS vars",
                          "#CCFF00" in html or "#ccff00" in html))
    results.append(_check("Gold primary #C5A46D present",
                          "#C5A46D" in html or "#c5a46d" in html))
    results.append(_check("Aurora deep navy #0A1628 present",
                          "#0A1628" in html or "#0a1628" in html))

    # ─── Typography & fonts ───────────────────────────────────
    results.append(_check("Lora font family referenced",
                          "'Lora'" in html or '"Lora"' in html))
    results.append(_check("Inter font family referenced",
                          "'Inter'" in html or '"Inter"' in html))
    results.append(_check("WOFF2 data URI (Lora latin) embedded",
                          "data:font/woff2;base64" in html))
    # At least 4 @font-face blocks (Lora latin+cyrillic + Inter latin+cyrillic)
    results.append(_check("4+ @font-face declarations",
                          html.count("@font-face") >= 4,
                          f"found {html.count('@font-face')}"))

    # ─── Theme system ─────────────────────────────────────────
    results.append(_check('data-theme="light" selector present',
                          '[data-theme="light"]' in html))
    results.append(_check('data-theme="dark" selector present',
                          '[data-theme="dark"]' in html))
    results.append(_check('data-theme="fun" selector present',
                          '[data-theme="fun"]' in html))

    # ─── ECharts bundle ───────────────────────────────────────
    # ECharts signature string (present in min.js)
    results.append(_check("ECharts bundle inline (not CDN ref)",
                          "echarts" in html and "cdn.jsdelivr" not in html
                          and "cdn.bootcss" not in html))

    # ─── Security ─────────────────────────────────────────────
    results.append(_check("Content-Security-Policy meta present",
                          "Content-Security-Policy" in html))
    results.append(_check("CSP uses sha256 hashes",
                          "'sha256-" in html))

    # Parse CSP directives for per-directive 'unsafe-inline' checks.
    # style-src-attr 'unsafe-inline' is LEGITIMATE (permits inline style=""
    # attributes for dynamic data-driven styling in sections.py). But
    # style-src / script-src MUST remain hash-only - these cover <style>
    # and <script> blocks where XSS via injection would execute.
    _csp_match = re.search(r'Content-Security-Policy[^>]+content="([^"]+)"', html)
    _csp = _csp_match.group(1) if _csp_match else ""
    _directives = {}
    for d in _csp.split(";"):
        d = d.strip()
        if not d:
            continue
        parts = d.split(None, 1)
        _directives[parts[0]] = parts[1] if len(parts) > 1 else ""

    style_src = _directives.get("style-src", "")
    script_src = _directives.get("script-src", "")
    results.append(_check("style-src uses hashes (no 'unsafe-inline')",
                          "'unsafe-inline'" not in style_src,
                          f"style-src: {style_src[:60]}..." if style_src else "missing"))
    results.append(_check("script-src uses hashes (no 'unsafe-inline')",
                          "'unsafe-inline'" not in script_src))
    results.append(_check("style-src-attr 'unsafe-inline' present (explicit, covers inline style='')",
                          "'unsafe-inline'" in _directives.get("style-src-attr", "")))
    results.append(_check("NO 'unsafe-eval' in CSP",
                          "'unsafe-eval'" not in html))
    results.append(_check("frame-ancestors 'none' in CSP",
                          "frame-ancestors 'none'" in html))

    # Hash coverage: every inline <style> and <script> block must match a CSP hash.
    _style_csp_hashes = set(re.findall(r"'sha256-([^']+)'", style_src))
    _script_csp_hashes = set(re.findall(r"'sha256-([^']+)'", script_src))
    _style_blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
    _script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    # Filter out <script src="..."> (external) - they don't need content hash
    _script_blocks = [s for s in _script_blocks if s.strip()]
    _style_matched = sum(
        1 for b in _style_blocks
        if base64.b64encode(hashlib.sha256(b.encode('utf-8')).digest()).decode() in _style_csp_hashes
    )
    _script_matched = sum(
        1 for b in _script_blocks
        if base64.b64encode(hashlib.sha256(b.encode('utf-8')).digest()).decode() in _script_csp_hashes
    )
    results.append(_check(
        "Every <style> block hash present in CSP style-src",
        _style_matched == len(_style_blocks),
        f"{_style_matched}/{len(_style_blocks)} blocks hashed"
    ))
    results.append(_check(
        "Every <script> block hash present in CSP script-src",
        _script_matched == len(_script_blocks),
        f"{_script_matched}/{len(_script_blocks)} blocks hashed"
    ))

    # ─── Structural (14 sections) ─────────────────────────────
    section_ids = ['cover', 'summary', 'findings', 'divider', 'key', 'mroas',
                   'share', 'table', 'timeline', 'recommend', 'method',
                   'sources', 'glossary', 'closing']
    present = sum(1 for s in section_ids if f'id="{s}"' in html)
    results.append(_check(f"14 section ids present", present == 14,
                          f"{present}/14"))

    # ─── Accessibility ───────────────────────────────────────
    results.append(_check("Skip-to-content link present",
                          'class="skip-link"' in html))
    results.append(_check("aria-hidden on decorative lime bars",
                          'aria-hidden="true"' in html))
    results.append(_check("lang='ru' on html root", 'lang="ru"' in html))
    results.append(_check("Viewport meta for responsive",
                          'name="viewport"' in html))

    # ─── Trust signals ────────────────────────────────────────
    results.append(_check("Report ID present (aurora-mmm-XX hash)",
                          "aurora-mmm-" in html))
    results.append(_check("Favicon SVG data URI",
                          "data:image/svg+xml;base64" in html))
    results.append(_check("OG meta tags (og:title)",
                          'property="og:title"' in html))
    results.append(_check("Methodology badge link",
                          '#method' in html))
    # 09.09.2026, внешний аудит: было `_conf in html`, а пустая строка входит в любой документ —
    # при пустом значении в таблице строк отчёт ушёл бы клиенту вовсе без метки, а сторож
    # остался бы зелёным. Непустоту требуем отдельным условием.
    _conf = _expected_confidentiality()
    results.append(_check("Confidentiality watermark",
                          bool(_conf) and _conf in html,
                          _conf if _conf else "🔴 значение в таблице строк пустое"))

    # ─── Size budget ─────────────────────────────────────────
    size_kb = len(html) / 1024
    results.append(_check(f"HTML size under 1.2 MB cap",
                          size_kb < 1200, f"{size_kb:.1f} KB"))

    # ─── Em dash (user-visible content only) ─────────────────
    # Exclude bundled ECharts Chinese i18n strings (third-party)
    # Heuristic: find em dashes NOT surrounded by CJK characters
    # 09.09.2026: здесь стоял обычный дефис вместо длинного тире, поэтому проверка
    # считала все дефисы подряд (CSS, атрибуты, base64) и не могла стать зелёной НИ НА
    # КАКОМ документе — 4863 «находки» на корректном отчёте. Проверка, неспособная дать
    # положительный ответ, бесполезна ровно так же, как неспособная дать отрицательный:
    # на её сигнал перестают смотреть. Символ ниже — длинное тире U+2014.
    # 09.09.2026, вторая правка: регулярка `.{2}—.{2}` была слепа втройне —
    # `.` не совпадает с переносом строки (тире в конце строки не находилось),
    # требовала по два символа с каждой стороны (тире у краёв документа пропускалось),
    # и шла непересекающимися совпадениями («aa—bb—cc» давало 1 вместо 2).
    # Контекст теперь берётся срезом: каждое вхождение рассматривается отдельно.
    #
    # 09.09.2026, третья правка: проверка объявлена про «user-visible content», а считала по
    # всему файлу — включая комментарии в <script> и <style>. Шесть «находок» на живой
    # выгрузке оказались комментариями разработчика, которых покупатель не видит никогда,
    # и один настоящий дефект в видимом тексте утонул бы среди них. Ниже из документа
    # вырезается всё, что не показывается человеку.
    visible = re.sub(r'<script.*?</script>', ' ', html, flags=re.S | re.I)
    visible = re.sub(r'<style.*?</style>', ' ', visible, flags=re.S | re.I)
    visible = re.sub(r'<!--.*?-->', ' ', visible, flags=re.S)

    non_cjk_em_dashes = 0
    for i, ch in enumerate(visible):
        if ch != '—':
            continue
        ctx = visible[max(0, i - 2):i + 3]
        # Считаем только если окружение не CJK (U+4E00-U+9FFF) — там тире чужое,
        # из встроенной китайской локали ECharts.
        if not any(0x4E00 <= ord(c) <= 0x9FFF for c in ctx):
            non_cjk_em_dashes += 1
    results.append(_check(f"No em dashes in user-visible content",
                          non_cjk_em_dashes == 0,
                          f"{non_cjk_em_dashes} found (ECharts CJK excluded)"))

    # ─── Summary ─────────────────────────────────────────────
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{passed}/{total} brand invariants passed")
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
