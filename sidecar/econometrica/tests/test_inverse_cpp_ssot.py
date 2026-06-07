"""Tests для CPP SSOT (INV-50, 2026-06-07).

Корень (live-аудит оптимизатора перед rc10): goal-seek `build_proportional_forward`
читал training CPP из pickle `cfg.unit_costs` (заморожен при обучении) для ТЕКУЩЕГО
бюджета, тогда как forward/decompose берут current CPP из `unitCosts` store (= project.json).
Расхождение → разный «текущий бюджет» между вкладками «От бюджета» (2.34 млрд) и
«От цели» (2.91 млрд) на одном экране (Кагоцел).

Фикс: `_resolve_current_unit_costs` — единый SSOT для current CPP:
override (request) > project.json.unit_costs > pickle cfg.unit_costs (legacy fallback).
training snapshot (`unit_costs_snapshot`) остаётся отдельно для Hill-нормализации.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from optimize.inverse import _resolve_current_unit_costs  # noqa: E402


def _write_project_json(d: Path, unit_costs: dict) -> None:
    (d / 'project.json').write_text(
        json.dumps({'unit_costs': unit_costs}, ensure_ascii=False), encoding='utf-8')


def test_ssot_project_json_wins_over_pickle_cfg(tmp_path):
    """project.json.unit_costs (current CPP) приоритетнее pickle cfg (training CPP)."""
    _write_project_json(tmp_path, {'TRPs': 94238.68})
    cfg = {'unit_costs': {'TRPs': 120000.0}}
    r = _resolve_current_unit_costs(str(tmp_path), cfg)
    assert r['TRPs'] == 94238.68  # SSOT = project.json, НЕ training-frozen pickle


def test_fallback_to_cfg_when_project_json_empty(tmp_path):
    """Пустой project.json.unit_costs → fallback на pickle cfg (legacy-проекты)."""
    _write_project_json(tmp_path, {})
    cfg = {'unit_costs': {'TRPs': 120000.0}}
    r = _resolve_current_unit_costs(str(tmp_path), cfg)
    assert r['TRPs'] == 120000.0


def test_fallback_to_cfg_when_no_project_json(tmp_path):
    """Нет project.json вовсе → fallback на pickle cfg (не падает)."""
    cfg = {'unit_costs': {'TRPs': 120000.0}}
    r = _resolve_current_unit_costs(str(tmp_path), cfg)
    assert r['TRPs'] == 120000.0


def test_override_wins_over_everything(tmp_path):
    """Явный override (из request/store) приоритетнее project.json и cfg."""
    _write_project_json(tmp_path, {'TRPs': 94238.68})
    cfg = {'unit_costs': {'TRPs': 120000.0}}
    r = _resolve_current_unit_costs(str(tmp_path), cfg, override={'TRPs': 50000.0})
    assert r['TRPs'] == 50000.0


def test_zero_and_nonpositive_values_ignored(tmp_path):
    """unit_costs с нулями/мусором → они отфильтрованы, валидные сохранены."""
    _write_project_json(tmp_path, {'TRPs': 94238.68, 'Empty': 0, 'Bad': None})
    cfg = {'unit_costs': {'TRPs': 120000.0}}
    r = _resolve_current_unit_costs(str(tmp_path), cfg)
    assert r['TRPs'] == 94238.68
    assert 'Empty' not in r and 'Bad' not in r


def test_all_zero_project_json_falls_back_to_cfg(tmp_path):
    """Если в project.json все CPP=0/невалидны → считается пустым → fallback cfg."""
    _write_project_json(tmp_path, {'TRPs': 0, 'X': None})
    cfg = {'unit_costs': {'TRPs': 120000.0}}
    r = _resolve_current_unit_costs(str(tmp_path), cfg)
    assert r['TRPs'] == 120000.0
