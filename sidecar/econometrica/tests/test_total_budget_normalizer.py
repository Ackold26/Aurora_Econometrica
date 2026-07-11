"""A6-1 (2026-07-10): тесты нормализатора имён каналов — исправление \b-матчинга
в snake_case строках и расширение стоп-листа агрегатными токенами.

Корень бага: в snake_case строках (total_media_budget) символ _ является
словесным символом в regex — \b не стоит между словом и _. Поэтому \btotal\b
не матчился в «total_media_budget» и колонка проходила как media-канал.

Правка: заменять _ → пробел перед regex-матчингом (только для целей matcher'а).
Дополнительно: добавлены budget/spend/media/overall/grand/gross + общий/расходы/затраты.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.narrative_adapter import _normalize_channel_name  # noqa: E402


# ─── Unit-тесты: агрегаты → None ─────────────────────────────────────────────

class TestNoneForAggregates:
    """Агрегатные колонки должны давать None — они не являются медиа-каналами."""

    def test_total_media_budget_snake(self):
        """A6-1 core: snake_case с total+media+budget — все токены стоп-слова."""
        assert _normalize_channel_name('total_media_budget') is None

    def test_total_budget_snake(self):
        assert _normalize_channel_name('total_budget') is None

    def test_media_budget_snake(self):
        assert _normalize_channel_name('media_budget') is None

    def test_total_spend_snake(self):
        assert _normalize_channel_name('total_spend') is None

    def test_media_spend_snake(self):
        assert _normalize_channel_name('media_spend') is None

    def test_budget_do_nds_cyrillic(self):
        assert _normalize_channel_name('Бюджет до НДС') is None

    def test_obshij_budget_cyrillic(self):
        assert _normalize_channel_name('Общий бюджет') is None

    def test_itogo_cyrillic(self):
        assert _normalize_channel_name('Итого') is None

    def test_grand_total_snake(self):
        assert _normalize_channel_name('grand_total') is None


# ─── Unit-тесты: живые каналы → НЕ None ─────────────────────────────────────

class TestNotNoneForRealChannels:
    """Реальные медиа-каналы должны возвращать непустую строку."""

    def test_tv_spend_snake(self):
        result = _normalize_channel_name('tv_spend')
        assert result is not None and result != ''

    def test_tv_spend_snake_label(self):
        """tv_spend → 'tv' (spend — стоп-слово, tv — живой канал)."""
        assert _normalize_channel_name('tv_spend') == 'tv'

    def test_digital_spend_snake(self):
        result = _normalize_channel_name('digital_spend')
        assert result is not None and result != ''

    def test_ooh_spend_snake(self):
        result = _normalize_channel_name('ooh_spend')
        assert result is not None and result != ''

    def test_performance_spend_snake(self):
        result = _normalize_channel_name('performance_spend')
        assert result is not None and result != ''

    def test_tv_plain(self):
        assert _normalize_channel_name('TV') == 'TV'

    def test_performance_budget_do_nds(self):
        """Performance Бюджет до НДС → Performance (бюджет+до+ндс — шум)."""
        assert _normalize_channel_name('Performance Бюджет до НДС') == 'Performance'

    def test_trps_brand_with_parens(self):
        """TRPs бренд (W 25-50) → без изменений (нет стоп-слов)."""
        assert _normalize_channel_name('TRPs бренд (W 25-50)') == 'TRPs бренд (W 25-50)'

    def test_specproekt_budget_do_nds(self):
        assert _normalize_channel_name('Спецпроект Бюджет ДО НДС') == 'Спецпроект'

    def test_olv_budget_snake(self):
        """olv_budget → 'olv' (budget — стоп-слово, olv — живой канал)."""
        assert _normalize_channel_name('olv_budget') == 'olv'

    def test_online_video_cyrillic(self):
        """Онлайн-видео → без изменений (нет стоп-слов)."""
        assert _normalize_channel_name('Онлайн-видео') == 'Онлайн-видео'

    def test_tv_cyrillic(self):
        assert _normalize_channel_name('ТВ') == 'ТВ'


# ─── Регресс A6-1b (аудит 2026-07-11): составные имена с квалификатором ───────
# 'media'/'overall'/'grand'/'gross' — квалификаторы, НЕ самостоятельные стоп-слова.
# Раньше 'social_media'→'social', 'Media Radar'→'Radar', голый 'media'→None.

class TestCompositeNamesWithQualifier:
    """Имя канала, где 'media'/'overall'/'gross' — часть составного имени,
    должно сохраняться целиком (снимается только чистый агрегат)."""

    def test_social_media_kept(self):
        assert _normalize_channel_name('social_media') == 'social media'

    def test_media_radar_kept(self):
        assert _normalize_channel_name('Media Radar') == 'Media Radar'

    def test_programmatic_media_kept(self):
        assert _normalize_channel_name('programmatic_media') == 'programmatic media'

    def test_overall_reach_kept(self):
        assert _normalize_channel_name('overall_reach') == 'overall reach'

    def test_gross_rating_points_kept(self):
        assert _normalize_channel_name('gross_rating_points') == 'gross rating points'

    def test_social_media_spend_stripped_to_channel(self):
        """social_media_spend → 'social media' (spend — шум, media — часть имени)."""
        assert _normalize_channel_name('social_media_spend') == 'social media'

    def test_bare_media_is_aggregate(self):
        """Голый 'media' без инструмента — агрегатная колонка → None."""
        assert _normalize_channel_name('media') is None

    def test_bare_overall_is_aggregate(self):
        assert _normalize_channel_name('overall') is None

    def test_media_budget_still_aggregate(self):
        """media_budget → 'media' → квалификатор → None (регресс не ослаб)."""
        assert _normalize_channel_name('media_budget') is None


# ─── Интеграционный тест с validate_data ─────────────────────────────────────

class TestIntegrationValidateData:
    """total_media_budget как сумма tv+digital: validator должен снять роль media."""

    @pytest.fixture()
    def data_file(self, tmp_path: Path) -> Path:
        rng = np.random.default_rng(42)
        n = 24
        dates = pd.date_range('2023-01-01', periods=n, freq='MS').strftime('%Y-%m-%d')
        tv = rng.uniform(1e6, 5e6, n).round(-3)
        digital = rng.uniform(0.5e6, 3e6, n).round(-3)
        sales = (10e6 + 1.5 * tv + 2.0 * digital + rng.normal(0, 2e5, n)).round(-3)
        total = tv + digital
        df = pd.DataFrame({
            'date': dates,
            'Продажи': sales,
            'tv_spend': tv,
            'digital_spend': digital,
            'total_media_budget': total,
        })
        out = tmp_path / 'data.xlsx'
        df.to_excel(out, index=False)
        return out

    def test_total_media_budget_role_unused(self, data_file: Path, tmp_path: Path):
        """total_media_budget должен получить роль 'unused', не 'media'."""
        from engines.validator import validate_data
        proj = tmp_path / 'proj'
        proj.mkdir()
        result = validate_data(str(data_file), str(proj))

        assert result.get('status') != 'error', f"validate_data вернул ошибку: {result}"

        cols_by_name = {c['name']: c for c in result.get('columns', [])}

        assert 'total_media_budget' in cols_by_name, (
            "Колонка total_media_budget должна присутствовать в columns"
        )
        assert cols_by_name['total_media_budget']['role'] == 'unused', (
            f"total_media_budget должна иметь role='unused', "
            f"получено: {cols_by_name['total_media_budget']['role']}"
        )

    def test_tv_and_digital_role_media(self, data_file: Path, tmp_path: Path):
        """tv_spend и digital_spend должны получить роль 'media'."""
        from engines.validator import validate_data
        proj = tmp_path / 'proj'
        proj.mkdir()
        result = validate_data(str(data_file), str(proj))

        cols_by_name = {c['name']: c for c in result.get('columns', [])}

        for ch in ('tv_spend', 'digital_spend'):
            assert ch in cols_by_name, f"Колонка {ch} должна присутствовать в columns"
            assert cols_by_name[ch]['role'] == 'media', (
                f"{ch} должна иметь role='media', получено: {cols_by_name[ch]['role']}"
            )

    def test_total_budget_warning_present(self, data_file: Path, tmp_path: Path):
        """Должен быть warning типа 'total_budget_as_media' для total_media_budget."""
        from engines.validator import validate_data
        proj = tmp_path / 'proj'
        proj.mkdir()
        result = validate_data(str(data_file), str(proj))

        warnings = result.get('warnings', [])
        total_budget_warnings = [
            w for w in warnings
            if w.get('type') == 'total_budget_as_media'
            and w.get('column') == 'total_media_budget'
        ]
        assert total_budget_warnings, (
            f"Ожидался warning total_budget_as_media для total_media_budget. "
            f"Warnings: {[w.get('type') for w in warnings]}"
        )
