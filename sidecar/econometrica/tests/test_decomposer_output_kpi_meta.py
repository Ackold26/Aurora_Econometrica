"""F-A (synthetic-truth аудит 2026-06-06): выходные kpi-метаданные decompose должны
отражать ОБУЧЕННЫЙ kpi_type (из pickle), а не дефолтить в monetary из мёртвого
v13_kpi.json (LOAD-1 dead-save). narrative_adapter:818 читает их из decompose result →
иначе count-KPI PPTX/HTML экспорт мислейблится как monetary/₽/ROI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.decomposer import _resolve_output_kpi_meta  # noqa: E402


class TestResolveOutputKpiMeta:
    def test_count_kpi_empty_v13_reflects_pickle(self):
        # v13_kpi.json не создаётся (dead path) → kpi_kind берётся из pickle-резолва
        m = _resolve_output_kpi_meta({}, kpi_kind='count', kpi_unit_cost=None)
        assert m['kpi_kind'] == 'count'              # НЕ 'monetary' (был баг)
        assert m['value_per_count_unit'] is None
        assert m['derived_mode'] == 'roi'            # frontend-концепт, дефолт

    def test_count_kpi_with_unit_cost(self):
        m = _resolve_output_kpi_meta({}, kpi_kind='count', kpi_unit_cost=150.0)
        assert m['kpi_kind'] == 'count'
        assert m['value_per_count_unit'] == 150.0    # из pickle/override, не None

    def test_monetary_kpi_unchanged(self):
        # монетарный — поведение как раньше
        m = _resolve_output_kpi_meta({}, kpi_kind='monetary', kpi_unit_cost=None)
        assert m['kpi_kind'] == 'monetary'
        assert m['value_per_count_unit'] is None

    def test_v13_present_takes_priority(self):
        # forward-compat: если save-path когда-то оживёт, v13_kpi имеет приоритет
        v13 = {'kpi_kind': 'monetary', 'derived_mode': 'effectiveness',
               'value_per_count_unit': 99.0, 'value_per_count_unit_label': '₽/шт'}
        m = _resolve_output_kpi_meta(v13, kpi_kind='count', kpi_unit_cost=150.0)
        assert m['kpi_kind'] == 'monetary'           # v13 override
        assert m['derived_mode'] == 'effectiveness'
        assert m['value_per_count_unit'] == 99.0
        assert m['value_per_count_unit_label'] == '₽/шт'
