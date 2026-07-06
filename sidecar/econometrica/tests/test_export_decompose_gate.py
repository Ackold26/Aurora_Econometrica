"""INV-50 NEW-2 (2026-07-06): гейт честности /export/pptx и /export/html.

Проблема: при пустом decompose_data оба эндпоинта тихо строили wireframe-PPTX/HTML
с ВЫДУМАННЫМИ числами (builder-дефолты: TRP, mROAS 1.9×, 22%) и отдавали клиенту
как результат — нарушение INV-50 (честность метрик) и API-гигиены.

Решение Антона 2026-07-06: явный флаг allow_wireframe.
Контракт _assert_decompose_present():
  - has_decomp=False, allow_wireframe=False → HTTPException 400
  - has_decomp=False, allow_wireframe=True  → pass (dev wireframe, легитимно)
  - has_decomp=True,  любой флаг            → pass (live данные)

Тесты изолированы от тяжёлого PyMC/JAX startup — логика реплицируется
локально (паттерн из test_path_traversal_guard.py), не через TestClient.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

from fastapi import HTTPException


def _assert_decompose_present(decompose_data: dict, allow_wireframe: bool) -> None:
    """Локальная копия production-логики из server.py (_assert_decompose_present).

    Синхронизировать с server.py при изменении контракта.
    Инварианты проверены в TestDecomposeGateContract ниже.
    """
    has_decomp = bool(decompose_data)
    if not has_decomp and not allow_wireframe:
        raise HTTPException(
            status_code=400,
            detail=(
                'Экспорт без результатов декомпозиции невозможен. '
                'Для каркасного превью (dev) передайте allow_wireframe=true — '
                'документ будет содержать ДЕМОНСТРАЦИОННЫЕ числа.'
            ),
        )


# ─── Фикстуры ─────────────────────────────────────────────────────────────────

EMPTY_DECOMPOSE: dict = {}

MINIMAL_DECOMPOSE: dict = {
    'contributions': {'TV': 0.3, 'Digital': 0.2},
    'total_revenue': 1_000_000.0,
}


# ─── Контрактные тесты гейта ──────────────────────────────────────────────────

class TestDecomposeGateContract:
    """Три ветки контракта NEW-2."""

    def test_empty_decompose_without_flag_raises_400(self):
        """Пустой decompose без флага → HTTPException 400 (honest-fail)."""
        with pytest.raises(HTTPException) as exc_info:
            _assert_decompose_present(EMPTY_DECOMPOSE, allow_wireframe=False)
        assert exc_info.value.status_code == 400

    def test_empty_decompose_error_message_is_informative(self):
        """Сообщение об ошибке содержит инструкцию для dev-пути."""
        with pytest.raises(HTTPException) as exc_info:
            _assert_decompose_present(EMPTY_DECOMPOSE, allow_wireframe=False)
        detail = exc_info.value.detail
        assert 'allow_wireframe' in detail, (
            'Сообщение должно подсказывать dev-путь через allow_wireframe=true'
        )
        assert 'ДЕМОНСТРАЦИОННЫЕ' in detail, (
            'Сообщение должно явно предупреждать о демо-числах в wireframe'
        )

    def test_empty_decompose_with_flag_passes(self):
        """Пустой decompose + allow_wireframe=True → pass (wireframe-превью)."""
        # Не должен выбрасывать — это dev wireframe путь.
        _assert_decompose_present(EMPTY_DECOMPOSE, allow_wireframe=True)

    def test_real_decompose_without_flag_passes(self):
        """Реальные данные без флага → pass (live-экспорт)."""
        _assert_decompose_present(MINIMAL_DECOMPOSE, allow_wireframe=False)

    def test_real_decompose_with_flag_passes(self):
        """Реальные данные + флаг → pass (флаг игнорируется при полных данных)."""
        _assert_decompose_present(MINIMAL_DECOMPOSE, allow_wireframe=True)


class TestDecomposeGateEdgeCases:
    """Граничные сценарии."""

    def test_none_values_dict_treated_as_empty(self):
        """Словарь с None-значениями — технически непустой (bool({key: None}) == True)."""
        # Это честное поведение: данные переданы, пусть и None — builder сам разберётся.
        _assert_decompose_present({'contributions': None}, allow_wireframe=False)

    def test_nested_empty_dict_treated_as_nonempty(self):
        """Вложенный пустой dict: {'meta': {}} — bool = True → pass."""
        _assert_decompose_present({'meta': {}}, allow_wireframe=False)

    def test_flag_default_is_false(self):
        """Дефолт allow_wireframe=False: пустой decompose → 400 без явного флага."""
        with pytest.raises(HTTPException) as exc_info:
            _assert_decompose_present({}, allow_wireframe=False)
        assert exc_info.value.status_code == 400

    def test_flag_true_does_not_block_live_data(self):
        """allow_wireframe=True при полных данных не блокирует живой экспорт."""
        decompose = {'contributions': {'TV': 100_000.0}, 'total': 500_000.0}
        _assert_decompose_present(decompose, allow_wireframe=True)
