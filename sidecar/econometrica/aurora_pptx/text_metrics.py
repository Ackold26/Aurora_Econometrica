# -*- coding: utf-8 -*-
"""Единый модуль измерения текста для PPTX-вёрстки (общий для overflow-ассерта).

Портирован из Smart Analytica (Dev/ROSST_AI_Media/tools/creative/text_metrics.py,
2026-06-07) — наиболее совершенный отчётный слой в Aurora. Generic, доменно не
связан.

ПОЧЕМУ: посимвольная аппроксимация ширины (0.52*size) расходится с реальной вёрсткой
PowerPoint для кириллицы в узких боксах → высота текста занижается, текст выходит за
бокс (autofit выключен) и наезжает на следующий блок. Econometrica правил это вручную
магическими числами кегля (builder.py:1465 «reduced 22pt to prevent overflow») — без
ассерта. Этот модуль меряет реальную ширину слов через PIL ImageFont фактическими
метриками шрифта (Georgia/Arial из системы) → точный word-wrap.

Graceful fallback: нет PIL/шрифта (не-Windows, урезанный рантайм) → посимвольная
аппроксимация, чтобы сборка/тест не падали.

Единицы:
  EMU: 914400 EMU = 1 inch = 96 px (@96 dpi);  12700 EMU = 1 pt
  pt → px: px = pt * 96/72 = pt * 4/3
"""
import os

EMU_PER_PX = 9525        # 914400 / 96
EMU_PER_PT = 12700
PX_PER_PT = 96.0 / 72.0  # 1.3333...

# Посимвольный fallback (если PIL недоступен)
_AVG_CHAR_W_FACTOR = 0.52

# Логические шрифты Econometrica-движка → файлы системных шрифтов Windows.
# Econometrica PPTX по умолчанию serif=Georgia, sans=Arial (builder.py:185-186).
# (regular, bold)
_FONT_FILES = {
    "Georgia":  ("georgia.ttf", "georgiab.ttf"),
    "Arial":    ("arial.ttf", "arialbd.ttf"),
    "Verdana":  ("verdana.ttf", "verdanab.ttf"),
    "Calibri":  ("calibri.ttf", "calibrib.ttf"),
    "Tahoma":   ("tahoma.ttf", "tahomabd.ttf"),
    "Consolas": ("consola.ttf", "consolab.ttf"),
    # OFL-кандидаты (если PPTX перейдёт на бренд-шрифты HTML-отчёта):
    "Inter":      ("Inter-Regular.ttf", "Inter-Bold.ttf"),
    "Montserrat": ("Montserrat-Regular.ttf", "Montserrat-Bold.ttf"),
}

try:
    from PIL import ImageFont as _ImageFont
except Exception:
    _ImageFont = None

_HERE = os.path.dirname(os.path.abspath(__file__))
# Каталоги поиска шрифтов: env override, локальный fonts/ движка, системные Windows.
_FONT_DIRS = [d for d in [
    os.environ.get("AURORA_FONTS_DIR"),
    os.path.join(_HERE, "fonts"),
    os.path.join(_HERE, "..", "aurora_html", "templates", "fonts"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
] if d]
_font_cache = {}


def font_path(font_name, bold=False):
    """Абсолютный путь к файлу шрифта (для встраивания в pptx). None если не найден."""
    reg, bd = _FONT_FILES.get(font_name, _FONT_FILES["Arial"])
    fname = bd if bold else reg
    for d in _FONT_DIRS:
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    return None


def _load_font(font_name, size_px, bold):
    """Загружает PIL-шрифт (кэш по name/bold/size_px). None если недоступен."""
    if _ImageFont is None:
        return None
    key = (font_name, bool(bold), int(size_px))
    if key in _font_cache:
        return _font_cache[key]
    p = font_path(font_name, bold)
    ft = None
    if p:
        try:
            ft = _ImageFont.truetype(p, int(size_px))
        except Exception:
            ft = None
    if ft is None and bold:
        ft = _load_font(font_name, size_px, False)
    _font_cache[key] = ft
    return ft


def _charwrap_count(word, width_px, font):
    """Сколько строк займёт одно слово длиннее строки (грубый посимвольный разрыв)."""
    if not word:
        return 1
    lines, cur = 1, ""
    for ch in word:
        if font.getlength(cur + ch) <= width_px or not cur:
            cur += ch
        else:
            lines += 1
            cur = ch
    return lines


def _wrap_lines_pil(text, width_px, font):
    """Точный жадный word-wrap по реальным метрикам шрифта. Возвращает число виз. строк."""
    if width_px <= 0:
        return 1
    total = 0
    for hard in str(text).split("\n"):
        if not hard.strip():
            total += 1
            continue
        cur = ""
        for word in hard.split(" "):
            trial = word if not cur else cur + " " + word
            if font.getlength(trial) <= width_px:
                cur = trial
            elif not cur:
                total += _charwrap_count(word, width_px, font)
                cur = ""
            else:
                total += 1
                cur = word
        if cur:
            total += 1
    return max(1, total)


def _wrap_lines_fallback(text, width_emu, size_pt):
    """Старая посимвольная аппроксимация (если PIL недоступен)."""
    width_pt = width_emu / float(EMU_PER_PT)
    char_w = max(1.0, size_pt * _AVG_CHAR_W_FACTOR)
    cpl = max(1, int(width_pt / char_w))
    total = 0
    for hard in str(text).split("\n"):
        if not hard.strip():
            total += 1
        else:
            total += max(1, -(-len(hard) // cpl))  # ceil
    return max(1, total)


def wrap_lines(text, width_emu, size_pt, font_name="Arial", bold=False):
    """Число визуальных строк, которые займёт text в боксе шириной width_emu при size_pt."""
    size_px = max(1, round(size_pt * PX_PER_PT))
    width_px = width_emu / float(EMU_PER_PX)
    font = _load_font(font_name, size_px, bold)
    if font is None:
        return _wrap_lines_fallback(text, width_emu, size_pt)
    return _wrap_lines_pil(text, width_px, font)


def _natural_line_px(font_name, size_px, bold):
    """Естественная высота строки шрифта (px): ascent+descent, пол 1.2*кегль."""
    ft = _load_font(font_name, size_px, bold)
    if ft is not None:
        try:
            asc, desc = ft.getmetrics()
            return max(asc + desc, 1.2 * size_px)
        except Exception:
            pass
    return 1.2 * size_px


def line_height_emu(size_pt, line_spacing=1.2, font_name="Arial", bold=False):
    """Высота строки (EMU) = естественная высота строки шрифта * line_spacing."""
    size_px = max(1, round(size_pt * PX_PER_PT))
    nat_pt = _natural_line_px(font_name, size_px, bold) / PX_PER_PT
    return int(round(nat_pt * line_spacing * EMU_PER_PT))


def text_height_emu(text, width_emu, size_pt, line_spacing=1.2, font_name="Arial", bold=False):
    """Высота текстового блока (EMU): число_строк * высота_строки."""
    n = wrap_lines(text, width_emu, size_pt, font_name, bold)
    return line_height_emu(size_pt, line_spacing, font_name, bold) * n
