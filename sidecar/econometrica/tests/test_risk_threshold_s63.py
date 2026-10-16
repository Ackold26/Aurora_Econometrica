"""Порог заголовка «Риск» (слайд «Рекомендация», s09) и страж «не фокусироваться на Cut» (s63, решение владельца 16.10).

Правило: «Риск» – когда Cut-каналов СТРОГО БОЛЬШЕ ПОЛОВИНЫ портфеля, и не меньше двух
(2 из 2, 2 из 3, 3 из 4, 3 из 5, 4 из 6 – да; 1 из 2, 2 из 4, 2 из 5, 3 из 6 – нет).
Страж: канал, на котором «Риск» предлагал «сфокусировать бюджет», сам Cut – заголовок не зовёт
фокусироваться на нём («Сократить A, B – явного канала для роста нет»).
Портфель из одного канала, он Cut: «Сократить A – явного канала для роста нет».
Отказ модели, несошедшаяся оптимизация и низкая инкрементальность – прежние тексты, «Риска» там нет.

Тесты – поведением: вызов `derive_action_headline` и сборка слайда s09 штатным построителем.
Помощники синтетических портфелей – из `test_headlines_hero_cut_s60`.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import test_headlines_hero_cut_s60 as H  # noqa: E402
import test_underperformers_unified as U  # noqa: E402
from aurora_pptx.builder import AuroraPPTXBuilder  # noqa: E402
from engines.channel_action import OPT_NOT_CONVERGED_TITLE  # noqa: E402
from engines.narrative_adapter import _derive_narrative_facts, derive_action_headline  # noqa: E402

_NO_GROWTH = "явного канала для роста нет"


def _portfolio(n: int, k: int):
    """n каналов, k из них Cut (mROAS 0.2, 0.3 …, худший первым). Первый канал при k < n – герой и
    получатель переброски (Scale); при k == n все каналы Cut и получатель – тоже Cut."""
    rows = []
    if n > k:
        rows.append(("S", "Scale", 5.0))
    rows.extend((f"H{i}", "Hold", 1.3) for i in range(1, n - k))
    rows.extend((f"C{i}", "Cut", round(0.1 + 0.1 * i, 2)) for i in range(1, k + 1))
    return H._syn(*rows)


def _headline(n: int, k: int, realloc: float = 100.0, hint: str = "scqar", **over):
    ch = _portfolio(n, k)
    return derive_action_headline(ch, H._syn_facts(ch, reallocation_mln=realloc, **over), hint) or ""


def _is_risk(h: str) -> bool:
    return h.startswith("Сократить ") and ("сфокусировать бюджет" in h or _NO_GROWTH in h)


# ─── граница порога по сетке N = 1…6 ────────────────────────────────────────

# (N, k) → «Риск»: k >= 2 и 2k > N
_GRID = [(n, k) for n in range(1, 7) for k in range(0, n + 1)]


@pytest.mark.parametrize("n, k", _GRID)
@pytest.mark.parametrize("realloc", [100.0, 0.1])
def test_risk_iff_cut_strict_majority_and_at_least_two(n, k, realloc):
    """Сетка N = 1…6, k = 0…N, переброска значимая и незначимая: «Риск» – ровно когда k >= 2 и 2k > N."""
    expected = k >= 2 and 2 * k > n
    h = _headline(n, k, realloc)
    if k == n == 1:
        assert h == f"Сократить C1 – {_NO_GROWTH}"  # одноканальный портфель – отдельная ветка (ниже)
        return
    assert _is_risk(h) == expected, (n, k, realloc, h)


def test_risk_table_boundaries_match_owner_decision():
    """Таблица решения владельца 16.10: границы по числу каналов, прописью."""
    yes = [(2, 2), (3, 2), (3, 3), (4, 3), (4, 4), (5, 3), (5, 4), (5, 5), (6, 4), (6, 5), (6, 6)]
    no = [(2, 1), (3, 1), (4, 2), (5, 2), (6, 2), (6, 3)]
    assert all(_is_risk(_headline(n, k)) for n, k in yes), [(n, k, _headline(n, k)) for n, k in yes if not _is_risk(_headline(n, k))]
    assert not any(_is_risk(_headline(n, k)) for n, k in no), [(n, k, _headline(n, k)) for n, k in no if _is_risk(_headline(n, k))]


# ─── именованные сценарии ───────────────────────────────────────────────────

def test_two_of_three_cut_is_risk_with_focus_on_scale_channel():
    """2 из 3: было «Перераспределить 100 млн руб в S – +5 пп к ROAS» (источник вычтен, порог не набирался),
    стало «Риск» – получатель S не Cut, фокус на нём остаётся."""
    assert _headline(3, 2) == "Сократить C1, C2 и сфокусировать бюджет на S"


def test_three_of_five_cut_is_risk():
    assert _headline(5, 3) == "Сократить C1, C2 и сфокусировать бюджет на S"


def test_two_of_two_cut_guard_removes_focus_on_cut_channel():
    """2 из 2 Cut: без стража было бы «… и сфокусировать бюджет на C2» (C2 сам Cut)."""
    h = _headline(2, 2)
    assert h == f"Сократить C1, C2 – {_NO_GROWTH}"
    assert "сфокусировать" not in h


def test_one_of_two_cut_is_not_risk():
    h = _headline(2, 1)
    assert not _is_risk(h) and h.startswith("Перераспределить"), h


def test_four_of_six_cut_is_risk_as_before():
    """4 из 6 – «Риск» и до s63 (граница четырёх и шести каналов не сдвинулась); 3 из 6 – нет, как раньше."""
    assert _headline(6, 4) == "Сократить C1, C2 и сфокусировать бюджет на S"
    assert not _is_risk(_headline(6, 3))
    assert _is_risk(_headline(4, 3)) and not _is_risk(_headline(4, 2))


def test_single_channel_portfolio_that_is_cut():
    """1 из 1: текст владельца. Раньше – «Портфель сбалансирован …» (переброска незначима) либо «Сократить C1 (… млн руб)»."""
    for realloc in (100.0, 0.1):
        assert _headline(1, 1, realloc) == f"Сократить C1 – {_NO_GROWTH}"


def test_single_channel_portfolio_that_is_not_cut_is_not_risk():
    h = _headline(1, 0)
    assert not _is_risk(h), h


def test_single_channel_cut_leaves_mroas_slide_unchanged():
    """Нижняя граница «не меньше двух»: слайд mROAS при одном Cut-канале не получает «Сократить неэффективные
    каналы …» (множественное число про один канал) – решение владельца про один канал касается только s09."""
    h = _headline(1, 1, hint="mroas")
    assert h == "Сбалансировать портфель по mROAS – один канал не доминирует", h


def test_guard_when_hero_is_cut_but_not_every_channel_is():
    """Получатель – герой, срезанный оптимизатором (Cut, mROAS 5), рядом Cut и Hold: 2 из 3 – «Риск» со стражем."""
    ch = H._syn(("H", "Hold", 1.3), ("A", "Cut", 0.3), ("B", "Cut", 5.0))
    f = H._syn_facts(ch, hero_channel="B", leader_channel="B", scale_destination_channel=None)
    assert derive_action_headline(ch, f, "scqar") == f"Сократить A, B – {_NO_GROWTH}"


def test_guard_only_for_cut_recipient_reduce_hero_keeps_focus_text():
    """Страж – ровно про Cut: получатель Reduce не трогается (вне решения владельца)."""
    ch = H._syn(("R", "Reduce", 5.0), ("A", "Cut", 0.3), ("B", "Cut", 0.5))
    f = H._syn_facts(ch, hero_channel="R", leader_channel="R", scale_destination_channel=None)
    assert derive_action_headline(ch, f, "scqar") == "Сократить A, B и сфокусировать бюджет на R"


def test_recipient_that_is_not_cut_keeps_focus_text_on_two_of_three():
    ch = H._syn(("S", "Scale", 5.0), ("A", "Cut", 0.3), ("B", "Cut", 0.5))
    assert derive_action_headline(ch, H._syn_facts(ch), "scqar") == "Сократить A, B и сфокусировать бюджет на S"


# ─── запреты стоят выше «Риска» ─────────────────────────────────────────────

@pytest.mark.parametrize("n, k", [(2, 2), (3, 2), (3, 3), (5, 3), (1, 1)])
def test_unconverged_optimization_keeps_its_own_title(n, k):
    assert _headline(n, k, optimization_converged=False) == OPT_NOT_CONVERGED_TITLE


@pytest.mark.parametrize("n, k", [(2, 2), (3, 2), (3, 3), (5, 3), (1, 1)])
def test_model_refused_keeps_its_own_title(n, k):
    assert _headline(n, k, model_refused=True) == "Модель не завершила расчёт корректно – переброска бюджета отключена"


@pytest.mark.parametrize("n, k", [(2, 2), (3, 2), (5, 3), (1, 1)])
def test_honest_narrative_keeps_its_own_title(n, k):
    h = _headline(n, k, honest_narrative=True, media_contribution_pct=4.0)
    assert h == "Перед перераспределением: диагностика низкой инкрементальности медиа"


# ─── слайд «Рекомендация» собранной презентации ─────────────────────────────

def _deck(names, spec):
    """Фикстура Kagocel, урезанная до перечисленных каналов; факты – штатно через адаптер."""
    data = U._scenario_data(spec=spec)
    data["channels"] = [c for c in data["channels"] if c["name"] in names]
    derived = _derive_narrative_facts(data["channels"], {"expected_lift_pct": 7.1}, None, None)
    keep = {k: data["narrative_facts"][k] for k in
            ("total_sales", "baseline_pct", "media_contribution_pct", "honest_narrative")}
    data["narrative_facts"] = {**data["narrative_facts"], **derived, **keep}
    prs = AuroraPPTXBuilder(copy.deepcopy(data)).build()
    return data, U._pptx_blocks(prs)


_TRPS = U._TRPS


def test_scqar_slide_two_of_three_cut():
    """TRPs и OLV – Cut, Social – Scale: на слайде «Риск», получатель Social; ОТВЕТ той же переброски."""
    data, (blocks, slide) = _deck([_TRPS, "OLV", "Social"], {"OLV": H._ch("Cut", mroas=0.6)})
    expected = f"Сократить {_TRPS}, OLV и сфокусировать бюджет на Social"
    assert derive_action_headline(data["channels"], data["narrative_facts"], "scqar") == expected
    assert expected in slide, slide
    assert f"из {_TRPS} в Social" in blocks["ОТВЕТ"], blocks["ОТВЕТ"]


def test_scqar_slide_two_of_two_cut_has_no_focus():
    """TRPs и OLV – оба Cut: на слайде страж, слова «сфокусировать» на слайде нет."""
    data, (blocks, slide) = _deck([_TRPS, "OLV"], {"OLV": H._ch("Cut", mroas=0.6)})
    expected = f"Сократить {_TRPS}, OLV – {_NO_GROWTH}"
    assert derive_action_headline(data["channels"], data["narrative_facts"], "scqar") == expected
    assert expected in slide, slide
    assert "сфокусировать" not in slide, slide
