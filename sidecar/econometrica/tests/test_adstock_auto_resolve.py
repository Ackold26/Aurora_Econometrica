"""Tests for _resolve_auto_adstock (NEW-1 fix).

Covers: строковый 'auto', dict-форма {'type': 'auto'}, fallback при ошибке,
non-auto каналы не трогаются, селектор не вызывается при отсутствии auto.

Намеренно НЕ используем OLS/Bayesian obuchenie — тестируем чистую логику
_resolve_auto_adstock изолированно через моки, чтобы тесты были мгновенными.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Добавляем sidecar/econometrica в sys.path (как делают остальные тесты)
sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.modeler import _resolve_auto_adstock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_result(selections: dict) -> dict:
    """Возвращает успешный ответ в формате select_adstock."""
    return {'status': 'ok', 'selections': selections, 'summary': 'mock'}


# ---------------------------------------------------------------------------
# Test 1: строковый 'auto' резолвится в конкретный тип
# ---------------------------------------------------------------------------

def test_auto_resolves_to_concrete_type():
    """adstock_config['tv'] = 'auto' → конкретный тип от селектора."""
    cfg = {'tv': 'auto', 'digital': 'geometric'}
    mock_result = _ok_result({'tv': {'type': 'weibull', 'confidence': 'strong'}})

    with patch('engines.modeler._resolve_auto_adstock.__module__') as _:
        pass  # placeholder — используем прямой patch ниже

    with patch('engines.adstock_selector.select_adstock', return_value=mock_result) as mock_sel:
        _resolve_auto_adstock(
            cfg,
            data_file='/fake/data.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital'],
            date_col='date',
        )

    assert cfg['tv'] == 'weibull', f"Expected 'weibull', got '{cfg['tv']}'"
    # digital не трогается
    assert cfg['digital'] == 'geometric'
    # селектор вызван ровно один раз, только для 'tv'
    mock_sel.assert_called_once()
    call_kwargs = mock_sel.call_args
    assert 'tv' in call_kwargs.kwargs.get('media_columns', call_kwargs.args[2] if len(call_kwargs.args) > 2 else [])


# ---------------------------------------------------------------------------
# Test 2: dict-форма {'type': 'auto'} тоже резолвится
# ---------------------------------------------------------------------------

def test_dict_form_auto():
    """adstock_config['tv'] = {'type': 'auto'} — резолвится как строковый 'auto'."""
    cfg = {'tv': {'type': 'auto'}, 'digital': 'geometric'}
    mock_result = _ok_result({'tv': {'type': 'geometric', 'confidence': 'weak'}})

    with patch('engines.adstock_selector.select_adstock', return_value=mock_result):
        _resolve_auto_adstock(
            cfg,
            data_file='/fake/data.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital'],
        )

    assert cfg['tv'] == 'geometric', f"Expected 'geometric', got '{cfg['tv']}'"
    # digital не трогается
    assert cfg['digital'] == 'geometric'


# ---------------------------------------------------------------------------
# Test 3: исключение в селекторе → fallback geometric, не падаем
# ---------------------------------------------------------------------------

def test_selector_exception_fallback_geometric():
    """Если select_adstock бросает исключение → fallback 'geometric', не пробрасывается."""
    cfg = {'tv': 'auto', 'digital': 'auto'}

    with patch('engines.adstock_selector.select_adstock', side_effect=RuntimeError('boom')):
        # Не должно пробросить исключение
        _resolve_auto_adstock(
            cfg,
            data_file='/fake/data.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital'],
        )

    assert cfg['tv'] == 'geometric', f"Expected geometric fallback, got '{cfg['tv']}'"
    assert cfg['digital'] == 'geometric', f"Expected geometric fallback, got '{cfg['digital']}'"


# ---------------------------------------------------------------------------
# Test 4: non-auto каналы не трогаются
# ---------------------------------------------------------------------------

def test_non_auto_untouched():
    """Каналы с явным типом ('geometric'/'weibull') не изменяются."""
    cfg = {'tv': 'weibull', 'digital': 'geometric', 'ooh': 'auto'}
    mock_result = _ok_result({'ooh': {'type': 'geometric', 'confidence': 'positive'}})

    with patch('engines.adstock_selector.select_adstock', return_value=mock_result):
        _resolve_auto_adstock(
            cfg,
            data_file='/fake/data.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital', 'ooh'],
        )

    assert cfg['tv'] == 'weibull', "Weibull канал не должен меняться"
    assert cfg['digital'] == 'geometric', "Geometric канал не должен меняться"
    assert cfg['ooh'] == 'geometric', "ooh должен резолвиться"


# ---------------------------------------------------------------------------
# Test 5: нет auto-каналов → селектор вообще не вызывается
# ---------------------------------------------------------------------------

def test_no_auto_selector_not_called():
    """Если ни один канал не 'auto', select_adstock не вызывается."""
    cfg = {'tv': 'geometric', 'digital': 'weibull'}

    with patch('engines.adstock_selector.select_adstock') as mock_sel:
        _resolve_auto_adstock(
            cfg,
            data_file='/fake/data.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital'],
        )

    mock_sel.assert_not_called()
    # конфиг не изменился
    assert cfg == {'tv': 'geometric', 'digital': 'weibull'}


# ---------------------------------------------------------------------------
# Test 6: селектор вернул status != 'ok' → fallback geometric
# ---------------------------------------------------------------------------

def test_selector_error_status_fallback_geometric():
    """Если select_adstock вернул status='error' → fallback geometric."""
    cfg = {'tv': 'auto'}

    with patch('engines.adstock_selector.select_adstock',
               return_value={'status': 'error', 'message': 'File not found'}):
        _resolve_auto_adstock(
            cfg,
            data_file='/nonexistent.xlsx',
            kpi_col='sales',
            media_cols=['tv'],
        )

    assert cfg['tv'] == 'geometric'


# ---------------------------------------------------------------------------
# Test 7: пустой adstock_config — no-op, не крашится
# ---------------------------------------------------------------------------

def test_empty_config_no_op():
    """Пустой adstock_config + media_cols без auto → no-op."""
    cfg = {}

    with patch('engines.adstock_selector.select_adstock') as mock_sel:
        _resolve_auto_adstock(
            cfg,
            data_file='/fake/data.xlsx',
            kpi_col='sales',
            media_cols=['tv', 'digital'],
        )

    mock_sel.assert_not_called()
    assert cfg == {}
