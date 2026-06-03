"""NaN/Inf в result-JSON → null (валидный JSON, парсится Rust serde_json).

Bug (2026-06-04 fresh-train аудит): вырожденная модель писала r_hat_max/intercept/
sigma=NaN в model-diagnostics.json голым json.dump → Rust serde_json (strict) падал →
project_load_results молча отдавал null → Отчёт «модель не загружена».
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.safe_io import sanitize_nonfinite  # noqa: E402


class TestSanitizeNonfinite:
    def test_nan_to_none(self):
        assert sanitize_nonfinite(float('nan')) is None
        assert sanitize_nonfinite(float('inf')) is None
        assert sanitize_nonfinite(float('-inf')) is None

    def test_finite_preserved(self):
        assert sanitize_nonfinite(3.14) == 3.14
        assert sanitize_nonfinite(0) == 0
        assert sanitize_nonfinite(-5) == -5

    def test_bool_preserved(self):
        # bool НЕ конвертируется (True/False — не числа в JSON-смысле)
        assert sanitize_nonfinite(True) is True
        assert sanitize_nonfinite(False) is False

    def test_numpy_floats(self):
        assert sanitize_nonfinite(np.float64('nan')) is None
        assert sanitize_nonfinite(np.float32('nan')) is None
        assert sanitize_nonfinite(np.float64(2.5)) == 2.5

    def test_nested(self):
        obj = {'metrics': {'r_hat_max': float('nan'), 'r2': 0.28},
               'list': [1.0, float('inf'), {'sigma': float('nan')}]}
        out = sanitize_nonfinite(obj)
        assert out['metrics']['r_hat_max'] is None
        assert out['metrics']['r2'] == 0.28
        assert out['list'] == [1.0, None, {'sigma': None}]

    def test_strict_json_roundtrip(self):
        # Главное: результат парсится СТРОГИМ парсером (как Rust serde_json)
        obj = {'r_hat_max': float('nan'), 'intercept': float('nan'), 'sigma': float('inf'), 'r2': 0.9}
        s = json.dumps(sanitize_nonfinite(obj))  # default allow_nan=True, но NaN уже убраны
        # строгий парс: parse_constant кидает на NaN/Infinity
        parsed = json.loads(s, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        assert parsed['r_hat_max'] is None
        assert parsed['sigma'] is None
        assert parsed['r2'] == 0.9
        assert 'NaN' not in s and 'Infinity' not in s

    def test_strings_and_other_preserved(self):
        assert sanitize_nonfinite('текст') == 'текст'
        assert sanitize_nonfinite(None) is None
