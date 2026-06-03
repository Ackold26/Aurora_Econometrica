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
