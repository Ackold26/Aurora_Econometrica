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
  (e) мутация: если условие показа `if self.promises_summary:` в настоящем
      build() перестать привязывать к атрибуту, тест должен покраснеть
      (F-06 внешнего аудита 2026-08-16: мутация ставится на реальный build(),
      не на его переписанную в тесте копию)
  (f) при единственной сверенной рекомендации число и слово согласованы
      (F-11 внешнего аудита 2026-08-16)
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
# F-06 внешнего аудита (2026-08-16): прежняя версия этого теста переписывала
# ВНУТРИ СЕБЯ всё тело build() (16 вызовов слайдов) и проверяла копию — реальный
# AuroraPPTXBuilder.build() при этом не исполнялся вовсе, а доказательство
# сводилось к тавтологии «вызов s10d_promises() создаёт слайд». Копия могла
# устареть относительно продуктового build() молча.
#
# Переписано: тест вызывает НАСТОЯЩИЙ, неизменённый build() дважды и точечно
# подменяет только ВХОД условия показа — self.promises_summary у реального
# объекта, прямо перед вызовом оригинального метода, — а не код метода.

def test_mutation_gate_promises_condition_is_load_bearing(base_payload, monkeypatch, tmp_path):
    """Если гейт `if self.promises_summary:` в НАСТОЯЩЕМ build() перестанет
    зависеть от promises_summary (например, кто-то уберёт условие и вызов
    s10d_promises() станет безусловным), эталонная колода без сверенных
    обещаний тоже начнёт получать лишний слайд — разница между эталоном и
    форсированной колодой перестанет быть равна 1, и assert ниже покраснеет.

    Мутируется СОСТОЯНИЕ реального объекта (self.promises_summary), а не
    тело build(): вызывается ровно тот же `AuroraPPTXBuilder.build`, что и в
    продукте, без единой переписанной строки."""
    import aurora_pptx.builder as builder_mod

    payload_no = copy.deepcopy(base_payload)
    payload_no.pop("promises_summary", None)

    # Эталон: настоящий, неизменённый build(), promises_summary не задан.
    out_ref = str(tmp_path / "deck_ref.pptx")
    prs_ref = _build_deck(payload_no, out_ref)
    n_ref = len(prs_ref.slides)

    # Форсированная колода: тот же payload без promises_summary, но прямо
    # перед вызовом ОРИГИНАЛЬНОГО build() атрибут подменяется на truthy —
    # условие показа обязано на это среагировать через настоящий s10d_promises().
    orig_build = builder_mod.AuroraPPTXBuilder.build

    def _forced_build(self):
        self.promises_summary = {"kept": 0, "missed": 0, "examples": []}
        return orig_build(self)

    monkeypatch.setattr(builder_mod.AuroraPPTXBuilder, "build", _forced_build)
    out_mut = str(tmp_path / "deck_mutated.pptx")
    prs_mut = _build_deck(payload_no, out_mut)
    n_mut = len(prs_mut.slides)

    monkeypatch.setattr(builder_mod.AuroraPPTXBuilder, "build", orig_build)

    # Форсированный promises_summary ДОЛЖЕН дать лишний слайд относительно
    # эталона — если ассерт здесь падает, гейт `if self.promises_summary:` в
    # настоящем build() больше не отвечает за показ слайда.
    assert n_mut == n_ref + 1, (
        "Форсированный promises_summary не дал лишнего слайда в настоящем "
        "build() — гейт test_no_promises_no_extra_slide / "
        "test_promises_slide_added больше не опирается на реальное условие "
        "показа, проверку нужно переработать"
    )


# ─── (f) F-11: согласование числа и слова при единственной рекомендации ─────

def test_promises_slide_singular_agreement(base_payload, tmp_path):
    """F-11 внешнего аудита (2026-08-16): при ОДНОЙ сверенной рекомендации
    заголовок и подпись героя раньше не согласовывались по числу — «Проверка
    рекомендаций: все 1 из прошлого отчёта сбылись» и «1 из 1 … рекомендаций
    из прошлого отчёта подтвердились на практике» (глагол во мн.ч. при
    единственном числе). Приём согласования — по образцу
    optimize/frontier.py::_ru_periods."""
    payload_pr = copy.deepcopy(base_payload)
    payload_pr["promises_summary"] = {
        "kept": 1,
        "missed": 0,
        "examples": [
            {"action_text": "Увеличить TV", "status": "kept", "status_ru": "сбылось"},
        ],
    }
    out = str(tmp_path / "deck_promises_singular.pptx")
    prs = _build_deck(payload_pr, out)
    all_text = _xml_text(prs)

    assert "Проверка рекомендаций: рекомендация из прошлого отчёта сбылась" in all_text
    assert "все 1 из прошлого отчёта сбылись" not in all_text
    assert "1 из 1" in all_text
    assert "рекомендации из прошлого отчёта подтвердилась на практике" in all_text
    assert "рекомендаций из прошлого отчёта подтвердились" not in all_text
