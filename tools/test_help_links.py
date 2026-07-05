"""Гейт целостности ссылок справки (src-tauri/help-econometrica, аудит 2026-07-05).

До этого теста справку защищал только sync_help_lists (AUTO-списки каналов):
битый якорь `href="#native"` или ссылка на несуществующий `template_*.xlsx`
не ловились ничем и доезжали до клиента (справка = bundle-ресурс приложения).

Проверяем для КАЖДОГО html справки:
  1. Внутренние якоря `href="#id"` указывают на существующий id= в том же файле.
  2. Относительные ссылки на локальные файлы (href/src: html/xlsx/js/css/png...)
     существуют в каталоге справки.
Внешние (http/https/mailto) не трогаем — сеть в гейте не нужна.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HELP_DIR = Path(__file__).resolve().parents[1] / 'src-tauri' / 'help-econometrica'
HTML_FILES = sorted(HELP_DIR.glob('*.html'))

# href="..." / src="..." (кавычки двойные — стиль справки).
_REF_RX = re.compile(r'(?:href|src)="([^"]+)"', re.IGNORECASE)
_ID_RX = re.compile(r'id="([^"]+)"', re.IGNORECASE)


def _refs(html_text: str):
    return _REF_RX.findall(html_text)


def _ids(html_text: str):
    return set(_ID_RX.findall(html_text))


@pytest.mark.parametrize('html_path', HTML_FILES, ids=lambda p: p.name)
def test_internal_anchors_resolve(html_path: Path):
    """Каждый href="#id" имеет id= в том же файле."""
    text = html_path.read_text(encoding='utf-8')
    ids = _ids(text)
    broken = [
        ref for ref in _refs(text)
        if ref.startswith('#') and len(ref) > 1 and ref[1:] not in ids
    ]
    assert not broken, f'{html_path.name}: битые якоря {broken}'


@pytest.mark.parametrize('html_path', HTML_FILES, ids=lambda p: p.name)
def test_local_file_links_exist(html_path: Path):
    """Каждая относительная ссылка на файл существует в каталоге справки."""
    text = html_path.read_text(encoding='utf-8')
    broken = []
    for ref in _refs(text):
        if ref.startswith(('#', 'http://', 'https://', 'mailto:', 'data:', 'tauri://')):
            continue
        # Отрезаем якорь/query: pipeline.html#step2 → pipeline.html
        target = ref.split('#')[0].split('?')[0]
        if not target:
            continue
        if not (HELP_DIR / target).exists():
            broken.append(ref)
    assert not broken, f'{html_path.name}: ссылки на несуществующие файлы {broken}'


def test_help_dir_not_empty():
    """Гейт не деградировал в вакуумный (справка на месте)."""
    assert len(HTML_FILES) >= 10, f'ожидалось ≥10 html в справке, найдено {len(HTML_FILES)}'


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
