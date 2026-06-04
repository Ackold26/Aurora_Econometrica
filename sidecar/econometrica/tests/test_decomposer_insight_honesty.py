"""INV-50: инсайт декомпозиции не должен короновать убыточный канал «самым
эффективным» и не должен печатать разные ROI как одинаковые «0.0×».

Найдено synthetic-truth аудитом (2026-06-03): на synth_fmcg медиа-сигнал ~5%,
движок ЧЕСТНО дал digital ROI 0.04× (вердикт «Глубоко убыточный»), но инсайт
короновал его «самый эффективный канал (ROI 0.0×)» — прямое противоречие вердикту.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.decomposer import _build_channel_insight, _fmt_roi, ROI_BREAKEVEN  # noqa: E402


def _ch(name, roi, gap=0.0, unit_smell=False):
    return {'name': name, 'roi': roi, 'efficiency_gap': gap, 'unit_smell': unit_smell}


class TestFmtRoi:
    def test_small_roi_two_decimals(self):
        # 0.04× и 0.02× ДОЛЖНЫ различаться, не оба «0.0×»
        assert _fmt_roi(0.04) == '0.04×'
        assert _fmt_roi(0.02) == '0.02×'
        assert _fmt_roi(0.04) != _fmt_roi(0.02)

    def test_large_roi_one_decimal(self):
        assert _fmt_roi(7.5) == '7.5×'
        assert _fmt_roi(12186.08) == '12186.1×'

    def test_none_and_nonnumeric_safe(self):
        assert _fmt_roi(None) == '0.00×'   # None → 0.0 → две цифры
        assert _fmt_roi(0) == '0.00×'
        assert _fmt_roi('abc') == '0×'     # неконвертируемое → except-ветка


class TestInsightHonesty:
    def test_profitable_top_is_crowned(self):
        channels = [_ch('TV', 3.5, gap=12), _ch('OOH', 0.6, gap=-8)]
        ins = _build_channel_insight(channels)
        assert 'TV - самый эффективный канал' in ins
        assert '3.5×' in ins

    def test_unprofitable_top_NOT_crowned(self):
        # Лучший канал сам убыточен (0.04× < breakeven) → НЕ «самый эффективный»
        channels = [_ch('digital_spend', 0.04, gap=2), _ch('tv_spend', 0.02, gap=-2)]
        ins = _build_channel_insight(channels)
        assert 'самый эффективный' not in ins
        assert 'Ни один канал не окупается' in ins
        assert 'digital_spend' in ins
        assert '0.04×' in ins  # честная точность, не «0.0×»

    def test_no_redistribute_advice_into_unprofitable_top(self):
        # Совет «перераспределить в top» НЕ должен возникать, если top убыточен
        channels = [_ch('digital_spend', 0.04, gap=12), _ch('tv_spend', 0.02, gap=-12)]
        ins = _build_channel_insight(channels)
        assert 'перераспределение' not in ins

    def test_unit_smell_channel_excluded_from_top(self):
        # REC-1-GAP regression: unit_smell-канал с артефактным ROI не коронуется
        channels = [
            _ch('TRPs', 12186.0, gap=10, unit_smell=True),
            _ch('Статьи', 2.5, gap=8),
            _ch('OOH', 0.5, gap=-5),
        ]
        ins = _build_channel_insight(channels)
        assert 'TRPs - самый эффективный' not in ins
        assert 'Статьи - самый эффективный канал' in ins

    def test_empty_channels(self):
        assert _build_channel_insight([]) == ''


class TestMoneyRoiUnavailableGate:
    """F-C (synthetic-truth retail probe 2026-06-06): count-KPI без kpi_unit_cost →
    per-channel ROI = нативное отношение (упак/₽), НЕсопоставимо. Особо ловит non-money
    каналы, чей unit_smell НЕ детектится по имени (binary promo_indicator, spend=9,
    unit_cost=1 → ROI-артефакт 50976× проходил name-based clean-фильтр и коронован)."""

    def test_money_roi_unavailable_no_crowning_of_artifact(self):
        channels = [
            _ch('promo_indicator', 50976.8, gap=33, unit_smell=False),  # имя без unit-hint
            _ch('tv_spend', 0.0, gap=-36),
            _ch('ooh_ots', 0.0, gap=-2, unit_smell=True),
        ]
        ins = _build_channel_insight(channels, money_roi_unavailable=True)
        assert 'самый эффективный' not in ins
        assert '50976' not in ins                 # артефактное число не печатается
        assert 'перераспределение' not in ins
        assert 'ценность единицы' in ins          # честная формулировка, согл. с вердиктами

    def test_money_roi_available_still_crowns_profitable_top(self):
        # backward compat: money ROI доступен → прежнее поведение
        channels = [_ch('TV', 3.5, gap=12), _ch('OOH', 0.6, gap=-8)]
        ins = _build_channel_insight(channels, money_roi_unavailable=False)
        assert 'TV - самый эффективный канал' in ins

    def test_default_param_is_backward_compat(self):
        # вызов без нового параметра = прежнее поведение (money ROI доступен)
        channels = [_ch('TV', 3.5, gap=12), _ch('OOH', 0.6, gap=-8)]
        assert 'TV - самый эффективный канал' in _build_channel_insight(channels)


class TestRoiArtifactGate:
    """F-C-extended (адверсариальный аудит 2026-06-06): артефактный ROI (>= ROI_ARTIFACT
    100×) НЕ коронуется даже на МОНЕТАРНОМ пути (money_roi_unavailable=False), где гейт
    money_roi_unavailable молчит, а name-based unit_smell промахивается мимо binary/
    индикаторных каналов без unit-keyword (promo_flag, distribution_flag)."""

    def test_artifact_roi_not_crowned_monetary_path(self):
        channels = [
            _ch('promo_flag', 50000.0, gap=33, unit_smell=False),  # артефакт, имя без hint
            _ch('tv_spend', 2.5, gap=10),
            _ch('ooh', 0.3, gap=-20),
        ]
        ins = _build_channel_insight(channels, money_roi_unavailable=False)
        assert 'promo_flag - самый эффективный' not in ins
        assert '50000' not in ins
        assert 'tv_spend - самый эффективный канал' in ins  # коронуем лучший ЛЕГИТ канал

    def test_all_channels_artifact_or_smell_no_crowning(self):
        channels = [_ch('flag_a', 9000.0, unit_smell=False), _ch('trp', 5000.0, unit_smell=True)]
        ins = _build_channel_insight(channels, money_roi_unavailable=False)
        assert 'самый эффективный' not in ins
        assert '9000' not in ins
        assert 'базовым спросом' in ins

    def test_legit_channels_unaffected_by_artifact_gate(self):
        # ROI < 100 → коронуется как раньше (порог не задевает нормальные ROI)
        channels = [_ch('TV', 8.0, gap=12), _ch('OOH', 0.6, gap=-8)]
        assert 'TV - самый эффективный канал' in _build_channel_insight(channels, money_roi_unavailable=False)
