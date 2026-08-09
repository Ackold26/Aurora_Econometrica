"""Сторож единого источника фразы о применимости результата.

🔴 Дефект (доказан зондом 2026-08-09, не гипотеза). Две шкалы жили порознь:

* отказ от рекомендаций (`utils/optimizer_honesty`: `refused=True` при
  R-hat ≥ 1.05 или дивергенциях выше порога);
* показатель качества модели MQS и его ступень (`utils/diagnostics`).

Боевой вызов при R-hat 1.06, нуле расхождений, R² 0.97, MAPE 3 и отношении
наблюдений к параметрам 12 давал MQS 88 «Отличное» И одновременно
`refused=True`. Клиент получал в одном документе «Модель не завершила расчёт
корректно – рекомендации по переброске бюджета отключены» и рядом «результаты
модели надёжны для принятия решений» / «Готовность к внедрению – можно
опираться на рекомендации в планировании».

Корень: `generate_diagnostics_summary` формировала фразу о надёжности ТОЛЬКО из
ступени MQS и признака тонкости данных — параметры сходимости ей передавались,
но она в них не смотрела вовсе. Этот же текст читает плашка на шаге обучения,
то есть клиент видел утверждение о надёжности ещё до оптимизации.

Сторож держит инвариант: **где печатается ступень MQS, там при отказе печатается
согласованная фраза из единого источника**. Проверяются все Python-поверхности
сразу — корень, веб-отчёт (две точки) и презентация (две точки). Зеркало Rust
стережёт отдельный файл: `test_reliability_statement_mirror.py`.

🔴 Гейтим ДЕЙСТВИЕ, не ДАННЫЕ: каждая проверка «фраза пришла» имеет парную
проверку «балл и ступень остались на месте». Спрятать показатели — это другой
дефект, не починка этого.
"""
from __future__ import annotations

import copy
import json
import os

import pytest

from aurora_html.sections import render_at_a_glance, render_sources
from aurora_pptx.builder import AuroraPPTXBuilder
from utils.diagnostics import (
    RELIABILITY_STATEMENT_DEPENDABLE,
    RELIABILITY_STATEMENT_REFUSED,
    generate_diagnostics_summary,
    reliability_statement,
)
from utils.optimizer_honesty import (
    model_did_not_converge,
    model_reliability_verdict,
    verdict_refuses,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

#: Обороты-эндорсменты, которые НЕ имеют права стоять рядом с отказом. Ищем
#: корни, а не точные фразы: точный список строк уже подводил (см. сторож
#: оговорки о тонких данных — «результаты не надёжны» проходил мимо списка).
_ENDORSEMENTS = (
    "Готовность к внедрению",
    "можно опираться на рекомендации",
    "Можно опираться на рекомендации",
    "Надёжный результат для принятия бюджетных решений",
)


def _ctx(payload: dict) -> dict:
    """Минимальный контекст для render_* (та же сборка, что в test_mqs_honest_absence)."""
    strings_path = os.path.join(os.path.dirname(_HERE), "aurora_html", "strings_ru.json")
    with open(strings_path, encoding="utf-8") as f:
        strings = json.load(f)
    return {
        "meta": payload.get("meta") or {},
        "facts": payload.get("narrative_facts"),
        "channels": payload.get("channels") or [],
        "diagnostics": payload.get("diagnostics") or {},
        "strings": strings,
        "kpi": {},
    }


def _pptx_text(prs) -> str:
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
    return "\n".join(parts)


def _payload(*, verdict: str | None) -> dict:
    """Доказанный зондом расклад: расчёт не сошёлся, а показатель отличный.

    Данных при этом достаточно (предел по тонким данным снят) — иначе
    сработала бы уже существующая оговорка и сторож ловил бы её, а не дефект.
    """
    with open(_FIXTURE, encoding="utf-8") as f:
        payload = copy.deepcopy(json.load(f))
    diag = payload["diagnostics"]
    diag["mqs_score"] = 88.0
    diag["mqs_tier_label"] = "Отличное"
    diag["r_hat_max"] = 1.06
    diag["ratio"] = 12.0
    diag["thinness_cap"] = None
    if verdict is None:
        diag.pop("honesty_verdict", None)
    else:
        diag["honesty_verdict"] = verdict
    return payload


@pytest.fixture(scope="module")
def refused_payload() -> dict:
    return _payload(verdict="unreliable")


@pytest.fixture(scope="module")
def reliable_payload() -> dict:
    return _payload(verdict="reliable")


# ─── Основание отказа: один предикат на две шкалы ────────────────────────────

@pytest.mark.parametrize(
    "r_hat,divergences,total_draws",
    [
        (1.00, 0, 4000),      # чисто
        (1.06, 0, 4000),      # доказанный зондом расклад
        (1.05, 0, 4000),      # ровно порог — отказ
        (1.04, 41, 4000),     # дивергенции выше 1% черновиков
        (1.04, 39, 4000),     # ниже порога при длинных цепях
        (1.04, 21, None),     # число черновиков неизвестно — работает абсолютный пол
        (1.04, 19, None),
    ],
)
def test_predicate_matches_optimizer_refusal(r_hat, divergences, total_draws):
    """`model_did_not_converge` обязан совпадать с веткой отказа вердикта.

    Это шов, ради которого всё и делалось: если предикат и вердикт разойдутся,
    вернётся ровно исходный дефект — текст скажет одно, гейт сделает другое.
    """
    diagnostics = {
        "metrics": {
            "r_hat_max": r_hat,
            "divergences": divergences,
            "ratio": 12.0,
            "mcmc": ({"chains": 4, "draws": total_draws // 4} if total_draws else {}),
        },
        "checks": {"convergence": r_hat < 1.05, "fit": True, "ratio": True},
        "mqs": {"tier": "excellent", "tier_label": "Отличное", "score": 88.0},
    }
    expected = bool(model_reliability_verdict(diagnostics)["refused"])
    actual = model_did_not_converge(r_hat, divergences, total_draws)
    assert actual == expected, (
        f"предикат отказа разошёлся с вердиктом при R-hat {r_hat}, "
        f"дивергенций {divergences}, черновиков {total_draws}: "
        f"предикат {actual}, вердикт {expected}"
    )


def test_refusing_verdict_string_matches_refused_flag():
    """`verdict_refuses` и поле `refused` описывают одно и то же событие."""
    for r_hat in (1.00, 1.06):
        diagnostics = {
            "metrics": {"r_hat_max": r_hat, "divergences": 0, "ratio": 12.0,
                        "mcmc": {"chains": 4, "draws": 1000}},
            "checks": {"convergence": r_hat < 1.05, "fit": True, "ratio": True},
            "mqs": {"tier": "excellent", "tier_label": "Отличное", "score": 88.0},
        }
        v = model_reliability_verdict(diagnostics)
        assert verdict_refuses(v["verdict"]) == bool(v["refused"]), v


# ─── Корень: вердикт модели ──────────────────────────────────────────────────

def _root(*, r_hat: float) -> dict:
    return generate_diagnostics_summary(
        r_squared=0.97, mape=3.0, rmse=100.0, r_hat_max=r_hat, divergences=0,
        n_obs=120, n_params=10, total_draws=4000,
    )


def test_root_verdict_drops_reliability_claim_when_refused():
    """Корень обязан смотреть на сходимость, а не только на ступень и тонкость."""
    summary = _root(r_hat=1.06)
    assert summary["mqs"]["tier"] == "excellent", summary["mqs"]
    verdict = summary["verdict"]
    assert RELIABILITY_STATEMENT_DEPENDABLE not in verdict, (
        f"расчёт не сошёлся, а вердикт утверждает надёжность: {verdict}"
    )
    assert RELIABILITY_STATEMENT_REFUSED in verdict, (
        f"вердикт не несёт согласованную фразу из единого источника: {verdict}"
    )


def test_root_keeps_the_numbers_when_refused():
    """Гейтим действие, не данные: балл, ступень и метрики остаются на месте."""
    summary = _root(r_hat=1.06)
    assert summary["mqs"]["score"] == 88.0, summary["mqs"]
    assert summary["mqs"]["tier_label"] == "Отличное"
    assert summary["metrics"]["r_hat_max"] == 1.06
    assert "97%" in summary["verdict"], "объяснённая доля обязана остаться в тексте"


def test_root_verdict_unchanged_when_model_converged():
    """Регресс: сошедшаяся модель с теми же числами — прежний текст."""
    verdict = _root(r_hat=1.00)["verdict"]
    assert RELIABILITY_STATEMENT_DEPENDABLE in verdict, verdict
    assert RELIABILITY_STATEMENT_REFUSED not in verdict, verdict


def test_long_chains_do_not_produce_false_refusal():
    """39 дивергенций на 4000 черновиках — порог 40, отказа быть не должно.

    Без переданного числа черновиков порог упал бы до абсолютного пола 20, и
    текст объявил бы отказ там, где оптимизатор его не объявляет: та же
    рассогласованность двух шкал, только в обратную сторону.
    """
    summary = generate_diagnostics_summary(
        r_squared=0.97, mape=3.0, rmse=100.0, r_hat_max=1.0, divergences=39,
        n_obs=120, n_params=10, total_draws=4000,
    )
    assert RELIABILITY_STATEMENT_REFUSED not in summary["verdict"], summary["verdict"]


# ─── Веб-отчёт: подпись под баллом (findings) ────────────────────────────────

def test_html_findings_carry_statement_when_refused(refused_payload):
    html = render_at_a_glance(_ctx(refused_payload))
    assert RELIABILITY_STATEMENT_REFUSED in html, (
        "подпись под баллом не несёт согласованную фразу при отказе"
    )
    for phrase in _ENDORSEMENTS:
        assert phrase not in html, (
            f"расчёт не сошёлся, а веб-отчёт обещает клиенту «{phrase}»"
        )


def test_html_findings_keep_score_when_refused(refused_payload):
    """Данные не прячем: балл и ступень остаются."""
    html = render_at_a_glance(_ctx(refused_payload))
    assert "MQS 88/100" in html, html[:400]
    assert "Отличное" in html


def test_html_findings_unchanged_when_reliable(reliable_payload):
    html = render_at_a_glance(_ctx(reliable_payload))
    assert RELIABILITY_STATEMENT_REFUSED not in html
    assert "Готовность к внедрению" in html, (
        "регресс: у сошедшейся модели прежняя подпись обязана остаться"
    )


# ─── Веб-отчёт: карточка «Качество модели и источники данных» ────────────────

def test_html_sources_card_carries_statement_when_refused(refused_payload):
    html = render_sources(_ctx(refused_payload))
    assert RELIABILITY_STATEMENT_REFUSED in html, (
        "карточка печатает ступень «Отличное» без единого слова об отказе"
    )
    assert "88<sub>/100</sub>" in html, "балл обязан остаться — гейтим действие, не данные"
    assert "Отличное" in html


def test_html_sources_card_unchanged_when_reliable(reliable_payload):
    html = render_sources(_ctx(reliable_payload))
    assert RELIABILITY_STATEMENT_REFUSED not in html
    assert "88<sub>/100</sub>" in html


# ─── Презентация: выводы и карточка MQS ──────────────────────────────────────

def test_pptx_carries_statement_when_refused(refused_payload):
    txt = _pptx_text(AuroraPPTXBuilder(refused_payload).build())
    assert txt.count(RELIABILITY_STATEMENT_REFUSED) >= 2, (
        "фраза обязана стоять и в выводах, и у карточки MQS — обе поверхности "
        f"печатают ступень. Найдено вхождений: {txt.count(RELIABILITY_STATEMENT_REFUSED)}"
    )
    for phrase in _ENDORSEMENTS:
        assert phrase not in txt, (
            f"расчёт не сошёлся, а колода обещает клиенту «{phrase}»"
        )


def test_pptx_keeps_score_and_tier_when_refused(refused_payload):
    txt = _pptx_text(AuroraPPTXBuilder(refused_payload).build())
    assert "MQS 88/100" in txt, "балл в выводах обязан остаться"
    assert "/ 100" in txt, "шкала карточки обязана остаться"
    assert "отличное" in txt.lower(), "ступень обязана остаться"


def test_pptx_unchanged_when_reliable(reliable_payload):
    txt = _pptx_text(AuroraPPTXBuilder(reliable_payload).build())
    assert RELIABILITY_STATEMENT_REFUSED not in txt
    assert "Можно опираться на рекомендации в планировании" in txt, (
        "регресс: у сошедшейся модели прежняя подпись обязана остаться"
    )


def test_pptx_refused_deck_has_no_overflow(refused_payload, tmp_path):
    """Новая фраза под карточкой MQS не должна ломать вёрстку колоды.

    Проверка не декоративная: внутри карточки свободно всего 0.36", и фраза,
    поставленная туда, столкнулась бы с сеткой метрик. Гейт тот же, что у
    test_pptx_overflow.py — он умеет краснеть (там же анти-вакуумный тест).
    """
    from aurora_pptx.check_overflow import check

    out = str(tmp_path / "deck_refused.pptx")
    AuroraPPTXBuilder(refused_payload).build().save(out)
    issues, n_slides = check(out)
    assert n_slides > 0
    detail = "\n".join(f"  слайд {s}: [{k}] {d}" for s, k, d in issues)
    assert issues == [], f"колода с отказом получила overflow/overlap:\n{detail}"


# ─── Сам источник ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", ["excellent", "good", "acceptable", "weak", "poor"])
def test_refusal_outranks_every_tier(tier):
    """Отказ старше ступени: показатель считается и при несошедшемся расчёте."""
    assert reliability_statement(tier, refused=True) == RELIABILITY_STATEMENT_REFUSED


def test_statement_is_client_grade_text():
    """Клиентская типографика: короткое тире, без длинного."""
    for text in (RELIABILITY_STATEMENT_REFUSED, RELIABILITY_STATEMENT_DEPENDABLE):
        assert "—" not in text, f"длинное тире в клиентском тексте: {text}"
