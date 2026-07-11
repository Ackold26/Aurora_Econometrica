"""Фаза 3, пласт 1 — KPI-паспорт: вердикты каналов count-aware.

Матрица тестов:
1. monetary mroas=1.5 → Scale или Hold (backward-compat)
2. count + vpcu=80, mroas=0.02 → eff=1.6 → Scale или Hold (НЕ Cut!)
3. count + vpcu=80, mroas=0.005 → eff=0.4 → Cut
4. count БЕЗ vpcu, mroas=0.02 → НЕ Cut по breakeven; вердикт Watch или Reduce/Scale по оптимизатору
5. effectiveness → money_roi_unavailable-ветка (НЕ Cut по breakeven)
6. Backward-compat: compute_channel_action(channel) без kwargs == прежний monetary результат
7. reasoning для count содержит cpu_per_label ('₽/лид'), НЕ 'mROAS'/'рубль'
8. Деградация (count без vpcu): reasoning содержит 'ценность единицы'; key НЕ 'Cut' при mroas=0.02
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.channel_action import compute_channel_action, ACTION_KEYS  # noqa: E402


def _make_channel(
    mroas: float = 1.0,
    *,
    current_spend: float = 1_000_000.0,
    optimal_spend: float | None = None,
    efficiency_gap: float = 0.0,
    untrained: bool = False,
    mroas_ci_low: float | None = None,
    mroas_ci_high: float | None = None,
) -> dict:
    """Минимальный channel-dict для тестов compute_channel_action."""
    ch: dict = {
        'mroas': mroas,
        'current_spend': current_spend,
        'efficiency_gap': efficiency_gap,
        'untrained': untrained,
    }
    if optimal_spend is not None:
        ch['optimal_spend'] = optimal_spend
    if mroas_ci_low is not None:
        ch['mroas_ci_low'] = mroas_ci_low
    if mroas_ci_high is not None:
        ch['mroas_ci_high'] = mroas_ci_high
    return ch


# ────────────────────────────────────────────────────────────────────────────
# 1. Backward-compat: monetary — всё как раньше
# ────────────────────────────────────────────────────────────────────────────

class TestMonetaryBackwardCompat:
    """monetary кейсы не меняют поведение."""

    def test_monetary_high_mroas_scale_or_hold(self):
        """mroas=1.5, optimizer +20% → Scale."""
        ch = _make_channel(mroas=1.5, optimal_spend=1_200_000.0)
        result = compute_channel_action(ch)
        assert result.key in ('Scale', 'Hold'), (
            f"Ожидалось Scale или Hold, получили {result.key}"
        )

    def test_monetary_low_mroas_cut(self):
        """mroas=0.5 < 0.8 → Cut."""
        ch = _make_channel(mroas=0.5)
        result = compute_channel_action(ch)
        assert result.key == 'Cut', f"Ожидалось Cut, получили {result.key}"

    def test_monetary_near_breakeven_reduce(self):
        """mroas=0.9 → Reduce."""
        ch = _make_channel(mroas=0.9)
        result = compute_channel_action(ch)
        assert result.key == 'Reduce', f"Ожидалось Reduce, получили {result.key}"

    def test_monetary_no_kwargs_same_result(self):
        """Вызов без kwargs == прежний monetary результат (backward-compat)."""
        ch = _make_channel(mroas=0.5)
        result_no_kwargs = compute_channel_action(ch)
        result_explicit = compute_channel_action(ch, kpi_kind='monetary')
        assert result_no_kwargs.key == result_explicit.key == 'Cut'

    def test_reasoning_contains_x_not_cpu(self):
        """monetary reasoning: '×', не '₽/лид', не 'CPU'."""
        ch = _make_channel(mroas=0.5)
        result = compute_channel_action(ch)
        assert '×' in result.reasoning or 'breakeven' in result.reasoning, (
            f"Reasoning должен содержать '×' или 'breakeven': {result.reasoning!r}"
        )
        assert '₽/лид' not in result.reasoning


# ────────────────────────────────────────────────────────────────────────────
# 2. count + vpcu: eff_mroas = mroas * vpcu
# ────────────────────────────────────────────────────────────────────────────

class TestCountWithVpcu:
    """count + vpcu: решение по eff_mroas, не по raw mroas."""

    def test_count_vpcu80_mroas002_not_cut(self):
        """Ключевой кейс: mroas=0.02 → raw < 0.8 → был Cut. eff=0.02*80=1.6 → НЕ Cut."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_050_000.0)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert result.key != 'Cut', (
            f"count+vpcu=80+mroas=0.02 НЕ должен давать Cut (eff=1.6), получили {result.key}"
        )
        assert result.key in ('Scale', 'Hold', 'Watch'), (
            f"Ожидалось Scale/Hold/Watch при eff=1.6, получили {result.key}"
        )

    def test_count_vpcu80_mroas002_scale_with_optimizer(self):
        """count + vpcu=80, mroas=0.02, optimizer +10% → Scale."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_100_000.0)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert result.key == 'Scale', (
            f"count+vpcu=80+optimizer+10%: ожидалось Scale, получили {result.key}"
        )

    def test_count_vpcu80_mroas0005_cut(self):
        """count + vpcu=80, mroas=0.005 → eff=0.4 < 0.8 → Cut."""
        ch = _make_channel(mroas=0.005)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert result.key == 'Cut', (
            f"count+vpcu=80+mroas=0.005: eff=0.4 → ожидалось Cut, получили {result.key}"
        )

    def test_count_vpcu80_mroas0125_hold(self):
        """count + vpcu=80, mroas=0.0125 → eff=1.0, gap=0 → Watch/Hold (near breakeven)."""
        ch = _make_channel(mroas=0.0125)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        # eff_mroas=1.0 — ровно на breakeven, threshold=1.1 для Hold → Watch или Reduce
        assert result.key in ('Watch', 'Reduce', 'Hold'), (
            f"count+vpcu=80+mroas=0.0125 (eff=1.0): ожидалось Watch/Reduce/Hold, получили {result.key}"
        )

    def test_count_reasoning_contains_cpu_per_label(self):
        """reasoning count+vpcu содержит cpu_per_label, НЕ 'mROAS', НЕ 'рубль'."""
        ch = _make_channel(mroas=0.005)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert '₽/лид' in result.reasoning, (
            f"Reasoning должен содержать '₽/лид': {result.reasoning!r}"
        )
        assert 'mROAS' not in result.reasoning, (
            f"Reasoning count-KPI не должен содержать 'mROAS': {result.reasoning!r}"
        )

    def test_count_reasoning_no_rub_word(self):
        """reasoning count+vpcu не содержит слова 'рубль'."""
        ch = _make_channel(mroas=0.02)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0, cpu_per_label='₽/лид')
        assert 'рубль' not in result.reasoning.lower(), (
            f"Reasoning не должен содержать 'рубль': {result.reasoning!r}"
        )


# ────────────────────────────────────────────────────────────────────────────
# 3. count БЕЗ vpcu (money_roi_unavailable=True) — деградация
# ────────────────────────────────────────────────────────────────────────────

class TestCountWithoutVpcu:
    """Деградация: count без vpcu → только optimizer-сигнал."""

    def test_count_no_vpcu_mroas002_not_cut(self):
        """mroas=0.02, без vpcu → НЕ Cut по breakeven (нет vpcu для пересчёта)."""
        ch = _make_channel(mroas=0.02)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            vpcu=None,
            money_roi_unavailable=True,
            cpu_per_label='₽/лид',
        )
        assert result.key != 'Cut', (
            f"count без vpcu с mroas=0.02 НЕ должен давать Cut, получили {result.key}"
        )

    def test_count_no_vpcu_default_mriu_watch(self):
        """count без vpcu, optimizer нейтральный → Watch."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            money_roi_unavailable=True,
            cpu_per_label='₽/лид',
        )
        assert result.key == 'Watch', (
            f"count без vpcu, optimizer neutral: ожидалось Watch, получили {result.key}"
        )

    def test_count_no_vpcu_optimizer_reduce(self):
        """count без vpcu, optimizer -10% → Reduce."""
        ch = _make_channel(mroas=0.02, optimal_spend=900_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            money_roi_unavailable=True,
            cpu_per_label='₽/лид',
        )
        assert result.key == 'Reduce', (
            f"count без vpcu + optimizer-10%: ожидалось Reduce, получили {result.key}"
        )

    def test_count_no_vpcu_optimizer_scale(self):
        """count без vpcu, optimizer +10% → Scale."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_100_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            money_roi_unavailable=True,
            cpu_per_label='₽/лид',
        )
        assert result.key == 'Scale', (
            f"count без vpcu + optimizer+10%: ожидалось Scale, получили {result.key}"
        )

    def test_count_no_vpcu_reasoning_contains_cennost(self):
        """Деградация: reasoning содержит 'ценность единицы'."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            money_roi_unavailable=True,
            cpu_per_label='₽/лид',
        )
        assert 'ценность единицы' in result.reasoning, (
            f"Reasoning деградации должен содержать 'ценность единицы': {result.reasoning!r}"
        )

    def test_count_no_vpcu_reasoning_contains_cpu_per_label(self):
        """Деградация: reasoning содержит cpu_per_label ('₽/лид')."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            money_roi_unavailable=True,
            cpu_per_label='₽/лид',
        )
        assert '₽/лид' in result.reasoning, (
            f"Reasoning деградации должен содержать '₽/лид': {result.reasoning!r}"
        )


# ────────────────────────────────────────────────────────────────────────────
# 4. effectiveness → money_roi_unavailable (независимо от vpcu)
# ────────────────────────────────────────────────────────────────────────────

class TestEffectivenessMode:
    """derived_mode='effectiveness' → money_roi_unavailable=True."""

    def test_effectiveness_mroas_small_not_cut(self):
        """effectiveness, mroas=0.02 (типичная доля%) → НЕ Cut."""
        ch = _make_channel(mroas=0.02, optimal_spend=1_000_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            vpcu=100.0,  # vpcu задан, но mode=effectiveness → mriu=True
            money_roi_unavailable=True,
            metric_short='Доля',
            cpu_per_label='%',
        )
        assert result.key != 'Cut', (
            f"effectiveness mode с mroas=0.02 НЕ должен давать Cut, получили {result.key}"
        )

    def test_effectiveness_optimizer_cut_strong_signal(self):
        """Optimizer ratio < 0.5 → Cut всегда (шаг 3 применяется до деградации)."""
        ch = _make_channel(mroas=0.02, optimal_spend=400_000.0)
        result = compute_channel_action(
            ch,
            kpi_kind='count',
            money_roi_unavailable=True,
            cpu_per_label='%',
        )
        assert result.key == 'Cut', (
            f"Optimizer ratio=0.4 < 0.5 → ожидалось Cut, получили {result.key}"
        )


# ────────────────────────────────────────────────────────────────────────────
# 5. Граничные кейсы (zero spend, untrained — не должны ломаться с kwargs)
# ────────────────────────────────────────────────────────────────────────────

class TestEdgeCasesWithKpiKwargs:
    """Шаги 1–2 (untrained/zero-spend) не зависят от kpi_kind."""

    def test_untrained_count_kpi_uncertain(self):
        ch = _make_channel(mroas=0.02, untrained=True)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0)
        assert result.key == 'Uncertain'

    def test_zero_spend_count_kpi_uncertain(self):
        ch = _make_channel(mroas=0.02, current_spend=0.0)
        result = compute_channel_action(ch, kpi_kind='count', vpcu=80.0)
        assert result.key == 'Uncertain'

    def test_result_key_always_valid(self):
        """Все ветки возвращают валидный ключ из ACTION_KEYS."""
        cases = [
            dict(kpi_kind='monetary'),
            dict(kpi_kind='count', vpcu=80.0),
            dict(kpi_kind='count', money_roi_unavailable=True),
            dict(kpi_kind='count', vpcu=80.0, money_roi_unavailable=False),
        ]
        mroas_values = [0.001, 0.02, 0.5, 1.0, 1.5, 3.0]
        for kwargs in cases:
            for mroas in mroas_values:
                ch = _make_channel(mroas=mroas)
                result = compute_channel_action(ch, **kwargs)
                assert result.key in ACTION_KEYS, (
                    f"Невалидный ключ {result.key!r} при mroas={mroas}, kwargs={kwargs}"
                )
