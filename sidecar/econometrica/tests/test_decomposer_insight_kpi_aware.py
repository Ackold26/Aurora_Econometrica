"""KPI-aware инсайт декомпозиции: утечка «ROI» в count/effectiveness режимах.

feat/econ-kpi-units (2026-07-11): _build_channel_insight параметризована по
kpi_kind/derived_mode/kpi_type. До правки — count и effectiveness каналы
получали «ROI X×» и «окупается», что противоречит их природе.

Тест-матрица:
  1. monetary  → содержит «ROI» и «×»
  2. count     → НЕ содержит «ROI», содержит «CPU» и/или «₽»
  3. effectiveness → НЕ содержит «ROI», НЕ содержит «окупает», говорит о доле
  4. backward-compat (без kpi-параметров) → результат аналогичен monetary
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.decomposer import _build_channel_insight  # noqa: E402


def _ch(name, roi, gap=0.0, unit_smell=False, share=None):
    """Минимальный channel-dict для _build_channel_insight.

    share — доля вклада (contribution_pct / share_of_effect); в реальном decompose
    всегда заполнена (decomposer.py ~:1054). Нужна для effectiveness-ветки инсайта.
    """
    d = {'name': name, 'roi': roi, 'efficiency_gap': gap, 'unit_smell': unit_smell}
    if share is not None:
        d['contribution_pct'] = share
        d['share_of_effect'] = share
    return d


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

# TV — profitable top, OOH — worst
_PROFITABLE_CHANNELS = [_ch('TV', 2.5, gap=8, share=60.0), _ch('OOH', 0.3, gap=-6, share=40.0)]

# Оба убыточны
_LOSS_CHANNELS = [_ch('Digital', 0.7, gap=3), _ch('Radio', 0.4, gap=-3)]


# ---------------------------------------------------------------------------
# Тест 1: monetary mode — «ROI X×»
# ---------------------------------------------------------------------------

class TestMonetaryInsight:
    def test_contains_roi_label(self):
        ins = _build_channel_insight(_PROFITABLE_CHANNELS, kpi_kind='monetary', derived_mode='roi')
        assert 'ROI' in ins, f"Ожидали «ROI» в monetary инсайте, получили: {ins!r}"

    def test_contains_times_symbol(self):
        ins = _build_channel_insight(_PROFITABLE_CHANNELS, kpi_kind='monetary', derived_mode='roi')
        assert '×' in ins, f"Ожидали «×» в monetary инсайте, получили: {ins!r}"

    def test_crowns_profitable_top(self):
        ins = _build_channel_insight(_PROFITABLE_CHANNELS, kpi_kind='monetary', derived_mode='roi')
        assert 'TV - самый эффективный канал' in ins

    def test_unprofitable_monetary_honest(self):
        ins = _build_channel_insight(_LOSS_CHANNELS, kpi_kind='monetary', derived_mode='roi')
        assert 'Ни один канал не окупается' in ins
        assert 'ROI' in ins


# ---------------------------------------------------------------------------
# Тест 2: count mode — «CPU», без «ROI»
# ---------------------------------------------------------------------------

class TestCountInsight:
    def test_no_roi_label(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='count',
            kpi_type='leads',
            derived_mode='roi',
        )
        assert 'ROI' not in ins, f"«ROI» не должен появляться в count инсайте, получили: {ins!r}"

    def test_contains_cpu_label(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='count',
            kpi_type='leads',
            derived_mode='roi',
        )
        assert 'CPU' in ins, f"Ожидали «CPU» в count инсайте, получили: {ins!r}"

    def test_contains_rubles_per_unit(self):
        # format_metric для count инвертирует ratio → ₽/лид (или ₽/ед. без паспорта)
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='count',
            kpi_type='leads',
            derived_mode='roi',
        )
        assert '₽' in ins, f"Ожидали «₽» в count инсайте, получили: {ins!r}"

    def test_no_roi_without_kpi_type(self):
        # Без kpi_type — backward-compat: «₽/ед.», но по-прежнему без «ROI»
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='count',
            kpi_type=None,
            derived_mode='roi',
        )
        assert 'ROI' not in ins

    def test_loss_count_no_okupается(self):
        # Убыточные count-каналы → не пишем «окупается»/«ROI»
        ins = _build_channel_insight(
            _LOSS_CHANNELS,
            kpi_kind='count',
            kpi_type='leads',
            derived_mode='roi',
        )
        assert 'ROI' not in ins
        assert 'окупает' not in ins
        # Должна быть нейтральная фраза про стоимость привлечения
        assert 'стоимость' in ins or 'CPU' in ins


# ---------------------------------------------------------------------------
# Тест 3: effectiveness mode — «доля», без «ROI»/«окупает»
# ---------------------------------------------------------------------------

class TestEffectivenessInsight:
    def test_no_roi_label(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='effectiveness',
            derived_mode='effectiveness',
        )
        assert 'ROI' not in ins, f"«ROI» не должен появляться в effectiveness инсайте, получили: {ins!r}"

    def test_no_okupается(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='effectiveness',
            derived_mode='effectiveness',
        )
        assert 'окупает' not in ins, f"«окупает» не должно быть в effectiveness инсайте, получили: {ins!r}"

    def test_mentions_share(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='effectiveness',
            derived_mode='effectiveness',
        )
        # Должны быть слова про долю
        assert 'доля' in ins or '%' in ins, f"Ожидали «доля» или «%» в effectiveness инсайте, получили: {ins!r}"

    def test_top_channel_named(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='effectiveness',
            derived_mode='effectiveness',
        )
        assert 'TV' in ins

    def test_worst_channel_named(self):
        ins = _build_channel_insight(
            _PROFITABLE_CHANNELS,
            kpi_kind='effectiveness',
            derived_mode='effectiveness',
        )
        assert 'OOH' in ins


# ---------------------------------------------------------------------------
# Тест 4: backward-compat — без kpi-параметров = monetary
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_no_params_equals_monetary(self):
        """Вызов без kpi-параметров должен давать тот же результат что monetary явно."""
        ins_default = _build_channel_insight(_PROFITABLE_CHANNELS)
        ins_monetary = _build_channel_insight(
            _PROFITABLE_CHANNELS, kpi_kind='monetary', derived_mode='roi'
        )
        assert ins_default == ins_monetary, (
            f"Backward-compat нарушен.\n"
            f"Дефолт: {ins_default!r}\n"
            f"Monetary явно: {ins_monetary!r}"
        )

    def test_no_params_contains_roi(self):
        ins = _build_channel_insight(_PROFITABLE_CHANNELS)
        assert 'ROI' in ins

    def test_money_roi_unavailable_still_works_without_kpi_params(self):
        # Старый вызов с только money_roi_unavailable — не ломается
        ins = _build_channel_insight(_PROFITABLE_CHANNELS, money_roi_unavailable=False)
        assert 'TV - самый эффективный канал' in ins
