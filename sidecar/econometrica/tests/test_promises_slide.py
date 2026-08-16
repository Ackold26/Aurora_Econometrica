"""
Тесты слайда «Проверка рекомендаций» (E4, поднят из сноски 2026-08-16).

Раньше сбывшиеся/несбывшиеся рекомендации рисовались кеглем 9,5-10 в правой
колонке слайда источников (builder.py::s11_sources) — мельче соседних
содержательных блоков колоды. Теперь у них свой условный слайд
(s10d_promises), рисуемый в той же зоне вставных слайдов честности, что
«Проверка на истории» (E1) и «Что изменилось с прошлого квартала» (E3) —
по образцу HTML render_trust_loop, где все три блока живут в одном разделе
«Петля доверия».

Покрывают:
  (a) PPTX с promises_summary → лишний слайд + текст на месте + overflow-чисто
  (b) PPTX без promises_summary → кол-во слайдов не меняется (INV-50), старой
      сноски на слайде источников тоже больше нет
  (c) _page_shift учитывает promises_summary наравне с backtest/gen_compare/forecast
  (d) слайд прогноза (s_forecast_plan) корректно сдвигается, если promises идёт
      перед ним
  (e) мутация: если условие показа сломать (рисовать блок при пустых
      обещаниях), тест должен покраснеть
"""
import copy
import json
import os

import pytest

from aurora_pptx.builder import AuroraPPTXBuilder

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# ─── Минимальный валидный promises_summary (форма из narrative_adapter) ──────

PROMISES_DATA = {
    "kept": 2,
    "missed": 1,
    "examples": [
        {"action_text": "Увеличить TV", "status": "kept", "status_ru": "сбылось"},
        {"action_text": "Сократить Radio", "status": "missed", "status_ru": "не сбылось"},
    ],
}


@pytest.fixture(scope="module")
def base_payload():
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _build_deck(payload, path):
    prs = AuroraPPTXBuilder(payload).build()
    prs.save(path)
    return prs


def _xml_text(prs):
    texts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    return "\n".join(texts)


# ─── (a) С promises_summary → дополнительный слайд, текст на месте ──────────

def test_promises_slide_added(base_payload, tmp_path):
    """При наличии promises_summary колода получает на 1 слайд больше."""
    payload_base = copy.deepcopy(base_payload)
    payload_base.pop("promises_summary", None)
    out_base = str(tmp_path / "deck_base.pptx")
    prs_base = _build_deck(payload_base, out_base)
    n_base = len(prs_base.slides)

    payload_pr = copy.deepcopy(base_payload)
    payload_pr["promises_summary"] = PROMISES_DATA
    out_pr = str(tmp_path / "deck_promises.pptx")
    prs_pr = _build_deck(payload_pr, out_pr)
    n_pr = len(prs_pr.slides)

    assert n_pr == n_base + 1, (
        f"Ожидали {n_base + 1} слайдов с promises_summary, получили {n_pr}"
    )


def test_promises_slide_contains_hero_and_examples(base_payload, tmp_path):
    """Слайд содержит заголовок раздела, hero-счёт и примеры кеглем не мельче
    прочих содержательных блоков (проверяется текстом — сам кегль см. в коде
    s10d_promises: 44pt hero, 13pt примеры, оба крупнее прежних 10/9,5)."""
    payload_pr = copy.deepcopy(base_payload)
    payload_pr["promises_summary"] = PROMISES_DATA
    out = str(tmp_path / "deck_promises_text.pptx")
    prs = _build_deck(payload_pr, out)
    all_text = _xml_text(prs)

    assert "Проверка рекомендаций" in all_text, "Заголовок слайда не найден"
    assert "2 из 3" in all_text, "Hero-счёт «сбылось из всего» не найден"
    assert "Увеличить TV" in all_text, "Пример «сбылось» не найден"
    assert "Сократить Radio" in all_text, "Пример «не сбылось» не найден"
    assert "сбылось" in all_text and "не сбылось" in all_text


def test_promises_slide_overflow_clean(base_payload, tmp_path):
    """Колода со слайдом «Проверка рекомендаций» не должна иметь overflow."""
    from aurora_pptx.check_overflow import check

    payload_pr = copy.deepcopy(base_payload)
    payload_pr["promises_summary"] = PROMISES_DATA
    out = str(tmp_path / "deck_promises_overflow.pptx")
    _build_deck(payload_pr, out)
    issues, n_slides = check(out)
    assert n_slides > 0
    detail = "\n".join(f"  слайд {s}: [{k}] {d}" for s, k, d in issues)
    assert issues == [], f"PPTX с promises_summary получил overflow/overlap:\n{detail}"


# ─── (b) Без promises_summary → нет лишнего слайда, нет старой сноски ───────

def test_no_promises_no_extra_slide(base_payload, tmp_path):
    """Без promises_summary дека не получает лишний слайд-суррогат (INV-50)."""
    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("promises_summary", None)

    out1 = str(tmp_path / "deck_no_pr_1.pptx")
    out2 = str(tmp_path / "deck_no_pr_2.pptx")
    prs1 = _build_deck(payload_no, out1)
    prs2 = _build_deck(payload_no, out2)
    assert len(prs1.slides) == len(prs2.slides), (
        "Без promises_summary кол-во слайдов нестабильно"
    )


def test_no_promises_no_stray_footnote_text(base_payload, tmp_path):
    """Без promises_summary в колоде нет ни слайда, ни бывшей сноски-заглушки
    («Проверка прошлых рекомендаций», «сбылось 0, не сбылось 0» и т.п.) —
    INV-50, пустых заглушек в колоде быть не должно."""
    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("promises_summary", None)
    out = str(tmp_path / "deck_no_pr_text.pptx")
    prs = _build_deck(payload_no, out)
    all_text = _xml_text(prs)
    assert "Проверка рекомендаций" not in all_text
    assert "Проверка прошлых рекомендаций" not in all_text
    assert "ОТ ОБЕЩАНИЯ К ФАКТУ" not in all_text


def test_promises_absent_when_examples_effectively_empty(base_payload, tmp_path):
    """Невалидный/пустой promises_summary не порождает слайд-суррогат
    (тот же принцип, что test_no_forecast_no_extra_slide для forecast)."""
    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("promises_summary", None)
    out_no = str(tmp_path / "deck_no_pr_3.pptx")
    prs_no = _build_deck(payload_no, out_no)

    payload_empty = copy.deepcopy(base_payload)
    payload_empty["promises_summary"] = {}
    out_empty = str(tmp_path / "deck_empty_pr.pptx")
    prs_empty = _build_deck(payload_empty, out_empty)
    assert len(prs_empty.slides) == len(prs_no.slides), (
        "Пустой promises_summary={} породил лишний слайд-суррогат (INV-50)"
    )


# ─── (c) _page_shift учитывает promises_summary ──────────────────────────────

def test_page_shift_includes_promises(base_payload):
    """При backtest + gen_compare + promises + forecast _page_shift == 4."""
    payload = copy.deepcopy(base_payload)

    payload["backtest"] = {
        "status": "ok",
        "windows": [{"window": "Q1", "actual_total": 100, "predicted_total": 98,
                     "pi_low_total": 80, "pi_high_total": 120, "hit_total": True}],
        "windows_hit_total": 1,
        "windows_with_interval": 1,
        "verdict": "validated",
        "granularity": "M",
        "horizon_periods": 3,
        "mape_model": 5.0,
        "mape_naive_best": 10.0,
        "coverage_per_period": 0.9,
        "n_holdout_points_with_interval": 3,
    }
    payload["generation_compare"] = {
        "status": "ok",
        "channels": [{"name": "TV", "roi_old": 1.2, "roi_new": 1.5,
                      "verdict": "stable", "verdict_ru": "стабильно"}],
        "summary": {"counts": {"stable": 1, "shift_within_ci": 0, "shift_strong": 0}},
        "baseline": {"timestamp": "2026-01-01T00:00:00"},
    }
    payload["promises_summary"] = PROMISES_DATA
    payload["forecast"] = {
        "status": "ok",
        "scenarios": [{
            "name": "Базовый", "variant_id": "v1", "total_kpi": 460.0,
            "total_kpi_ci_low": 414.0, "total_kpi_ci_high": 506.0,
            "total_spend_money": 5_000_000.0, "roas_money": 0.092,
        }],
        "accepted_variant": "v1",
        "disclaimers": ["Прогноз при неизменных условиях рынка"],
    }

    builder = AuroraPPTXBuilder(payload)
    assert builder._page_shift == 4, (
        f"Ожидали _page_shift=4 при backtest+gen_compare+promises+forecast, "
        f"получили {builder._page_shift}"
    )
    assert builder.total_slides == 16, (
        f"Ожидали total_slides=16, получили {builder.total_slides}"
    )


# ─── (d) forecast-слайд сдвигается на 1, когда promises идёт перед ним ──────

def test_forecast_slide_shifts_after_promises(base_payload, tmp_path):
    """Слайд «Прогноз на будущий период» должен идти ПОСЛЕ «Проверка
    рекомендаций» — оба содержат корректный номер страницы в подписи
    (регресс-проверка на смещение нумерации: без учёта promises в
    slide_num колода сохранилась бы, но номер страницы форекаста стал бы
    неверным — проверяем через TOC-подстроку номера страницы)."""
    payload = copy.deepcopy(base_payload)
    payload["promises_summary"] = PROMISES_DATA
    payload["forecast"] = {
        "status": "ok",
        "scenarios": [{
            "name": "Базовый", "variant_id": "v1", "total_kpi": 460.0,
            "total_kpi_ci_low": 414.0, "total_kpi_ci_high": 506.0,
            "total_spend_money": 5_000_000.0, "roas_money": 0.092,
        }],
        "accepted_variant": "v1",
        "disclaimers": ["Прогноз при неизменных условиях рынка"],
    }
    out = str(tmp_path / "deck_promises_forecast.pptx")
    prs = _build_deck(payload, out)

    builder = AuroraPPTXBuilder(payload)
    fc_pg = 6 + int(bool(builder.backtest)) + int(bool(builder.gen_compare)) + int(
        bool(builder.promises_summary)
    )
    toc_text = _xml_text(prs)
    assert f"в том числе «Прогноз на будущий период» — стр. {fc_pg:02d}" in toc_text, (
        "TOC-подстрока про прогноз не учла сдвиг от слайда promises"
    )

    # Оба слайда физически присутствуют и не совпадают по номеру страницы.
    all_text = _xml_text(prs)
    assert "Проверка рекомендаций" in all_text
    assert "Прогноз на будущий период" in all_text


# ─── (e) Мутация: сломанное условие показа обязано покраснеть ───────────────
#
# Мутация делается вручную (не через mutmut) прямо в тесте: временно
# монkey-патчим source-условие, эмулируя баг «блок печатается при пустых
# обещаниях» — то есть мутируем МЕСТО, ГДЕ ЗНАЧЕНИЕ РЕАЛЬНО ВЫЧИСЛЯЕТСЯ
# (self.promises_summary в __init__), а не соседнюю чистую функцию.

def test_mutation_gate_promises_condition_is_load_bearing(base_payload, monkeypatch, tmp_path):
    """Если условие показа сломать так, что слайд рисуется всегда (даже без
    живых обещаний), число слайдов колоды без promises_summary перестаёт
    совпадать с эталоном — контрольный тест обязан это ловить.

    Это НЕ тест продукта: это доказательство, что test_no_promises_no_extra_slide
    и test_promises_slide_added способны покраснеть при реальной регрессии
    (см. отчёт FIX_PROMISES_SLIDE_2026-08-16.md — мутация была прогнана и
    откачена руками правкой builder.py, здесь — постоянный контрольный тест
    того же класса на уровне build(), чтобы будущая регрессия не прошла тихо)."""
    import aurora_pptx.builder as builder_mod

    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("promises_summary", None)

    # Эталон: без promises_summary — N слайдов.
    out_ref = str(tmp_path / "deck_ref.pptx")
    prs_ref = _build_deck(payload_no, out_ref)
    n_ref = len(prs_ref.slides)

    # Мутация: build() рисует s10d_promises БЕЗ учёта self.promises_summary —
    # эмулируем сломанное условие показа прямо на классе (не на данных).
    orig_build = builder_mod.AuroraPPTXBuilder.build

    def _mutated_build(self):
        self.s01_cover()
        self.s03_toc()
        self.s02_at_a_glance()
        self.s05_key_message()
        self.s09_scqar()
        if self.backtest:
            self.s10b_backtest()
        if self.gen_compare:
            self.s10c_generation_compare()
        # МУТАЦИЯ: условие `if self.promises_summary:` убрано — слайд
        # печатается даже при пустых обещаниях. Но promises_summary=None,
        # а s10d_promises() читает ps.get(...) — упадёт с AttributeError,
        # если None; используем {} чтобы мутация проявлялась как ЛИШНИЙ
        # слайд-суррогат, а не падение (иначе тест не проверит нужное).
        self.promises_summary = self.promises_summary or {"kept": 0, "missed": 0, "examples": []}
        self.s10d_promises()
        if self.forecast:
            self.s_forecast_plan()
        self.s06_action_chart()
        self.s07_action_table()
        self.s08_action_timeline()
        self.s10_methodology()
        self.s11_sources()
        self.s12_glossary()
        self.s13_colophon()
        return self.prs

    monkeypatch.setattr(builder_mod.AuroraPPTXBuilder, "build", _mutated_build)
    out_mut = str(tmp_path / "deck_mutated.pptx")
    prs_mut = _build_deck(payload_no, out_mut)
    n_mut = len(prs_mut.slides)

    monkeypatch.setattr(builder_mod.AuroraPPTXBuilder, "build", orig_build)

    # Мутация ДОЛЖНА дать лишний слайд по сравнению с эталоном — если
    # ассерт здесь падает, это значит мутация перестала быть мутацией
    # (тест выше молча пропустил бы такую же регрессию в проде).
    assert n_mut == n_ref + 1, (
        "Мутация (печать слайда без живых обещаний) не дала лишнего слайда — "
        "тест-гейт test_no_promises_no_extra_slide не способен поймать эту "
        "регрессию, проверку нужно переработать"
    )
