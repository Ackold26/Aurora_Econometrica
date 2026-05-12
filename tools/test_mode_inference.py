"""Tests для utils/mode_inference.py - v1.3.0 derived mode (ADR-015)."""
from __future__ import annotations

import pytest

import sys
from pathlib import Path
SIDECAR_ROOT = Path(__file__).resolve().parent.parent / 'sidecar' / 'econometrica'
sys.path.insert(0, str(SIDECAR_ROOT))

from utils.mode_inference import (
    derive_mode,
    derive_mode_with_explanation,
    get_input_metrics_summary,
    is_mixed_mode,
)


# ─── Базовые 4 режима ───────────────────────────────────────────────────────

def test_all_monetary_derives_roi():
    inputs = {'tv': 'monetary', 'olv': 'monetary', 'performance': 'monetary'}
    assert derive_mode(inputs) == 'roi'


def test_all_physical_derives_effectiveness():
    inputs = {'tv': 'physical', 'olv': 'physical', 'performance': 'physical'}
    assert derive_mode(inputs) == 'effectiveness'


def test_mixed_derives_manual():
    inputs = {'tv': 'monetary', 'olv': 'physical', 'performance': 'monetary'}
    assert derive_mode(inputs) == 'manual'


def test_empty_dict_derives_roi_default():
    assert derive_mode({}) == 'roi'


# ─── Edge cases ─────────────────────────────────────────────────────────────

def test_single_monetary_channel():
    assert derive_mode({'tv': 'monetary'}) == 'roi'


def test_single_physical_channel():
    assert derive_mode({'tv': 'physical'}) == 'effectiveness'


def test_two_channels_one_each():
    """2 канала - один monetary, один physical → manual."""
    inputs = {'tv': 'monetary', 'olv': 'physical'}
    assert derive_mode(inputs) == 'manual'


def test_many_channels_all_monetary():
    inputs = {f'channel_{i}': 'monetary' for i in range(100)}
    assert derive_mode(inputs) == 'roi'


def test_many_channels_all_physical():
    inputs = {f'channel_{i}': 'physical' for i in range(100)}
    assert derive_mode(inputs) == 'effectiveness'


def test_invalid_metric_raises():
    with pytest.raises(ValueError, match='invalid metric'):
        derive_mode({'tv': 'unknown'})


def test_invalid_metric_in_one_channel_raises():
    """Один bad value - error даже если остальные OK."""
    with pytest.raises(ValueError):
        derive_mode({'tv': 'monetary', 'olv': 'something_else'})


# ─── is_mixed_mode helper ───────────────────────────────────────────────────

def test_is_mixed_mode_true():
    assert is_mixed_mode({'tv': 'monetary', 'olv': 'physical'})


def test_is_mixed_mode_false_for_roi():
    assert not is_mixed_mode({'tv': 'monetary', 'olv': 'monetary'})


def test_is_mixed_mode_false_for_effectiveness():
    assert not is_mixed_mode({'tv': 'physical', 'olv': 'physical'})


# ─── get_input_metrics_summary ──────────────────────────────────────────────

def test_summary_counts_correctly():
    inputs = {'tv': 'monetary', 'olv': 'physical', 'perf': 'monetary', 'pr': 'physical'}
    summary = get_input_metrics_summary(inputs)
    assert summary == {'monetary': 2, 'physical': 2}


def test_summary_zero_counts():
    summary = get_input_metrics_summary({})
    assert summary == {'monetary': 0, 'physical': 0}


# ─── derive_mode_with_explanation ───────────────────────────────────────────

def test_explanation_for_roi_mentions_money():
    result = derive_mode_with_explanation({'tv': 'monetary', 'olv': 'monetary'})
    assert result['mode'] == 'roi'
    assert '₽' in result['explanation']
    assert 'ROI' in result['explanation']


def test_explanation_for_effectiveness_mentions_physical():
    result = derive_mode_with_explanation({'tv': 'physical', 'olv': 'physical'})
    assert result['mode'] == 'effectiveness'
    assert 'физических' in result['explanation'] or 'физическ' in result['explanation']


def test_explanation_for_manual_mentions_mixed():
    result = derive_mode_with_explanation({'tv': 'monetary', 'olv': 'physical'})
    assert result['mode'] == 'manual'
    assert 'мешан' in result['explanation'].lower() or 'mixed' in result['explanation'].lower()
