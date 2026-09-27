"""Слайд «Методология»: полный список диагностики с сертификатом помещается.

s51: на образце для покупателя (16 слайдов, слайд 13) фраза критерия
совпадения «проверка стороннего – ветвь «другое зерно при полном расчёте»:
расхождение до 5 %» шла в колонке значений в три строки и уходила за линию
подвала (+0.22") поверх сноски о приорах. Общий гейт `test_pptx_overflow.py`
этого не видел: фикстура Кагоцела собрана без сертификата, и список
диагностики на ней – четыре метрики вместо девяти строк.

Здесь та же фикстура получает сертификат с содержимым образца s51 (значения
перенесены из данных проекта `_demo_samples_s51/_project`, длины строк как в
переданной презентации) – это наибольший список, какой строит
`строки_сертификата`: четыре метрики + отпечаток, зерно, отпечаток данных,
перенос эффекта, совпадение расчётов. Проверка – `check()` по всей
презентации, без фильтров.
"""
import copy
import json
import os

import pytest

from aurora_pptx.builder import AuroraPPTXBuilder
from aurora_pptx.check_overflow import check

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "kagocel_builder_payload.json")

# Сертификат образца s51 (results/model-diagnostics.json → builder payload),
# без полей, которые слайд не читает.
_CERT_S51 = {
    "status": "issued",
    "hash": "3836a805c4dc2ea3965d12af19d2e5c87a3b02bbdba2e863fd5a37bb8d2e3fc3",
    "reproducibility": {"status": "recorded", "seed": 42, "seed_source": "default"},
    "data_fingerprint": {
        "status": "recorded",
        "content": {
            "algo": "aurora-frame-v1",
            "sha256": "2d90df7243c8ee6fb6e0cf66aaef4b527966413b1f4e0916206c45dbba7f7e33",
            "n_rows": 136, "n_cols": 13,
        },
        "file": {
            "algo": "sha256-full-file",
            "sha256": "d11c2f4bada7a2c018c1d7eb505b1d30ef8934414986340a77d6b4c84b034a9b",
            "size_bytes": 17114, "file_name": "synth_fmcg_brand_planning.xlsx",
        },
    },
    "adstock_protocol": {
        "status": "recorded",
        "channels": [
            {"name": n, "requested": None, "resolved": "geometric", "by": "default"}
            for n in ("ТВ бюджет", "Онлайн-видео бюджет",
                      "Наружная реклама бюджет", "Performance бюджет")
        ],
    },
    "repro_tolerance": {
        "status": "declared",
        "applicable": {
            "mode": "other_seed_full",
            "title": "другое зерно при полном расчёте",
            "tolerances": {"roi": 5.0, "contribution_pct": 1.5},
        },
    },
}

# Самая длинная ветвь критерия – та же фраза на слайде длиннее образца.
_BRANCH_WIDE = {
    "mode": "reduced_or_other_env",
    "title": "сокращённый расчёт, другая среда или другие настройки",
    "tolerances": {"roi": 10.0, "contribution_pct": 3.0},
}


def _variant(name):
    cert = copy.deepcopy(_CERT_S51)
    diag_patch = {}
    if name == "wide_branch":
        cert["repro_tolerance"]["applicable"] = copy.deepcopy(_BRANCH_WIDE)
    elif name == "hierarchical":
        diag_patch["hierarchical"] = {
            "enabled": True,
            "channel_categories": {"ТВ бюджет": "brand", "Performance бюджет": "performance"},
        }
    elif name == "ols_deterministic":
        diag_patch["engine"] = "ols"
        cert["reproducibility"] = {"status": "deterministic"}
        cert["repro_tolerance"] = {"status": "deterministic"}
    elif name == "absent_criterion":
        cert["repro_tolerance"] = {"status": "absent"}
    return cert, diag_patch


@pytest.fixture(scope="module")
def payload():
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _methodology_slide(prs):
    for i, slide in enumerate(prs.slides, start=1):
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        if "ДИАГНОСТИКА" in texts:
            return i, texts
    raise AssertionError("слайд методологии («ДИАГНОСТИКА») не найден")


@pytest.mark.parametrize("variant", [
    "s51_sample", "wide_branch", "hierarchical", "ols_deterministic", "absent_criterion",
])
def test_methodology_slide_with_full_certificate_fits(payload, tmp_path, variant):
    data = copy.deepcopy(payload)
    cert, diag_patch = _variant(variant)
    data["certificate"] = cert
    data.setdefault("diagnostics", {}).update(diag_patch)

    prs = AuroraPPTXBuilder(data).build()
    out = str(tmp_path / f"deck_{variant}.pptx")
    prs.save(out)

    # Анти-вакуумность: на слайде действительно наибольший список – девять
    # строк диагностики, включая длинную фразу критерия совпадения.
    _, texts = _methodology_slide(prs)
    assert "Совпадение расчётов" in texts
    assert texts.count("Совпадение расчётов") == 1
    labels = {"Отпечаток", "Отпечаток данных (содержимое)", "Перенос эффекта"}
    assert labels <= set(texts), f"сертификат не дошёл до слайда: {sorted(labels - set(texts))}"

    issues, n_slides = check(out)
    assert n_slides > 0
    detail = "\n".join(f"  слайд {s}: [{k}] {d}" for s, k, d in issues)
    assert issues == [], f"презентация получила overflow/overlap:\n{detail}"
