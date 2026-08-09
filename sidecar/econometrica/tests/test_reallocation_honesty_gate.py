"""Переброска бюджета не строится на несошедшейся модели (09.08).

Регресс-тест на дефект «ЖДЁТ РЕШЕНИЯ ВЛАДЕЛЬЦА» из журнала блока: отчёты не
читали model_reliability.refused ни разу, поэтому один документ мог нести
одновременно «Модель ненадёжна – переброска отключена» (баннер) и директиву
«Перераспределить N млн ₽» (заголовок/ответ SCQAR). Эталон поведения — живой
экран OptimizeStep.svelte: applyOptimal() выходит сразу при refused=true,
слайдеры не двигаются, но цифры расчёта с экрана не исчезают.

Тест ловит рецидив на обеих сторонах узла: derive_action_headline (общая
функция для HTML и PPTX, единая точка гейта) и answer_body в builder.py
(отдельный узел SCQAR, гейтится независимо тем же флагом).
"""
from engines.narrative_adapter import derive_action_headline, _derive_narrative_facts


def _channels():
    return [
        {"name": "TV", "spend": 1_000_000, "contribution": 1_500_000,
         "mroas": 1.5, "roi": 1.5, "action": "Scale"},
        {"name": "OOH", "spend": 500_000, "contribution": 300_000,
         "mroas": 0.6, "roi": 0.6, "action": "Cut"},
    ]


def test_derive_narrative_facts_propagates_model_refused():
    """model_reliability.refused из optimize_data обязан долететь в facts —
    иначе гейт ниже по цепочке нечем поставить."""
    channels = _channels()
    optimize_data = {
        "model_reliability": {"verdict": "unreliable", "refused": True},
        "expected_lift_pct": 12.0,
    }
    facts = _derive_narrative_facts(channels, optimize_data, None, None)
    assert facts["model_refused"] is True


def test_derive_narrative_facts_not_refused_by_default():
    channels = _channels()
    optimize_data = {"expected_lift_pct": 12.0}
    facts = _derive_narrative_facts(channels, optimize_data, None, None)
    assert facts["model_refused"] is False


def test_action_headline_refused_replaces_directive_all_hints():
    """При refused=true ни один из четырёх слайдов не получает директиву
    (Нарастить/Сократить/Перераспределить/Консолидировать) — только честное
    сообщение об отказе."""
    channels = _channels()
    facts = {
        "model_refused": True,
        "expected_lift_pct": 12.0,
        "reallocation_mln": 5.0,
        "leader_channel": "TV",
        "hero_channel": "TV",
        "underperformer_names": ["OOH"],
        "honest_narrative": False,
        "media_contribution_pct": 50.0,
    }
    for hint in ("scqar", "mroas", "portfolio", "timeline"):
        headline = derive_action_headline(channels, facts, hint)
        assert headline is not None, f"{hint}: гейт не должен возвращать None (fallback к wireframe-тексту)"
        assert "не завершила расчёт корректно" in headline, f"{hint}: {headline!r}"
        for verb in ("Нарастить", "Сократить", "Перераспределить", "Консолидировать", "Защитить"):
            assert verb not in headline, f"{hint}: директива просочилась мимо гейта: {headline!r}"


def test_action_headline_not_refused_keeps_directive():
    """Мутация: гейт обязан молчать, когда refused=false — иначе он не
    точечный, а глушит директиву всегда."""
    channels = _channels()
    facts = {
        "model_refused": False,
        "expected_lift_pct": 12.0,
        "reallocation_mln": 5.0,
        "leader_channel": "TV",
        "hero_channel": "TV",
        "underperformer_names": [],
        "honest_narrative": False,
        "media_contribution_pct": 50.0,
    }
    headline = derive_action_headline(channels, facts, "mroas")
    assert headline is not None
    assert "не завершила расчёт корректно" not in headline
