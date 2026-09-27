"""s51 (аудит s50 L-6): доля выборок в пояснении к диапазону максимума.

`round(share * 100)` при 0 < share < 0.005 печатал «у 0% выборок» рядом с условием
«доля больше нуля», а при 0.995 ≤ share < 1 – «100%», хотя за границей максимум
не у всех выборок. Входы выбраны так, чтобы прежний и новый код давали РАЗНЫЙ
текст: 0.004 («0%» против «менее 1%») и 0.996 («100%» против «более 99%»).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize.frontier import _share_of_samples_ru  # noqa: E402

_FRONTIER_SRC = Path(__file__).parent.parent / 'optimize' / 'frontier.py'


@pytest.mark.parametrize('share, expected', [
    (0.004, 'менее 1%'),
    (0.0001, 'менее 1%'),
    (0.005, 'менее 1%'),  # round(0.5) == 0 – банковское округление
    (0.12, '12%'),
    (0.5, '50%'),
    (0.994, '99%'),
    (0.996, 'более 99%'),
    (1.0, '100%'),
])
def test_share_of_samples_text(share, expected):
    assert _share_of_samples_ru(share) == expected


def test_nonzero_share_never_printed_as_zero_or_full():
    """Ни одна доля строго между 0 и 1 не печатается как «0%» или «100%»."""
    for i in range(1, 1000):
        text = _share_of_samples_ru(i / 1000)
        assert text not in ('0%', '100%'), f'{i / 1000} → {text!r}'


def test_frontier_client_text_has_no_bare_share_rounding():
    """Сторож по исходнику: в тексте пояснения доля выборок идёт только через
    `_share_of_samples_ru`, а не голым `round(share… * 100)`."""
    src = _FRONTIER_SRC.read_text(encoding='utf-8')
    bare = re.findall(r'round\(\(?share_\w+[^)]*\*\s*100\)', src)
    assert bare == [], f'голое округление доли выборок в frontier.py: {bare}'
