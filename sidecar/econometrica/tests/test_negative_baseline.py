"""P0.6: проверка канона «отрицательный базовый уровень» и её совместимость.

Риск, названный планом заранее и подтверждённый зондом: новый ключ живёт в той же
структуре, которую правит инструмент пересчёта оценки качества
(`tools/recompute_mqs.py`) и которую читает вердикт, гейтящий советы по бюджету
(`utils/optimizer_honesty.model_reliability_verdict`).

Зонд уточнил постановку: пересчёт НЕ перезаписывает диагностику целиком — он
сливает секции (`mqs`, `verdict`, `checks` заменяются, `metrics` дополняется,
верхний уровень сохраняется). Поэтому ключ кладётся на верхний уровень; внутри
`checks` он исчезал бы при первом же пересчёте. Тесты ниже закрепляют ровно это.

Решение владельца 2026-08-03: вердикт надёжности НЕ трогаем — сначала считаем и
показываем, влияние на гейт советов обсуждается отдельно, после замера переходов
на эталонных проектах. Тест «вердикт не изменился» стережёт это решение.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.negative_baseline import compute_negative_baseline  # noqa: E402


def _samples(intercept_mu: float, n_draws: int = 500, sd: float = 0.1, seed: int = 0, n: int | None = None):
    """Выборки свободного члена вокруг заданного среднего (нормализованная шкала)."""
    rng = np.random.RandomState(seed)
    return rng.normal(intercept_mu, sd, n if n is not None else n_draws)


# ── Сам расчёт ──────────────────────────────────────────────────────────────

def test_здоровая_модель_молчит():
    """База уверенно положительна, разброс достаточный → «годно»."""
    res = compute_negative_baseline(
        intercept_samples=_samples(-0.5),
        control_betas_samples=np.zeros((0, 500)),
        x_control_norm=np.zeros((30, 0)),
        y_mean=5000.0, y_std=5000.0,
    )
    assert res is not None
    assert res['prob_negative'] == 0.0
    assert res['verdict'] == 'ok'
    assert res['detectable'] is True


def test_низкий_разброс_даёт_неприменимо_а_не_годно():
    """🔴 Замер 2026-08-03: на типовом проекте проверка НЕ МОЖЕТ провалиться.

    Свободный член имеет приор Normal(0, 0.5) в нормализованной шкале, поэтому
    при разбросе продаж 8% от среднего база уходит в минус только на 26 сигмах
    приора. Живой прогон подтвердил: три набора, построенные как заведомо
    больные, дали «годно». Подавать такой результат как «проверено» — ложное
    утверждение продукта о себе, поэтому вердикт «проверка неприменима».
    """
    res = compute_negative_baseline(
        intercept_samples=_samples(-0.5),
        control_betas_samples=np.zeros((0, 500)),
        x_control_norm=np.zeros((30, 0)),
        y_mean=6800.0, y_std=525.0,
    )
    assert res['verdict'] == 'not_applicable'
    assert res['detectable'] is False
    assert res['sigmas_needed'] > 20
    # Восстановление масштаба на месте: (−0,5)·525 + 6800 ≈ 6537.
    assert 6400 < res['baseline_mean'] < 6700


def test_провал_засчитывается_даже_при_низкой_чувствительности():
    """Если база УЖЕ в минусе — это факт, а не вопрос чувствительности."""
    res = compute_negative_baseline(
        _samples(-14.0, sd=0.2), None, None, 6800.0, 525.0)
    assert res['verdict'] == 'fail'
    assert res['detectable'] is False


def test_завышенный_вклад_медиа_ловится():
    """Модель «съела» весь базовый уровень: без рекламы продажи отрицательны.

    Ровно тот случай, ради которого проверка написана: вклад медиа приписан с
    избытком, остаток вытеснен ниже нуля, и все ROI завышены.
    """
    # y_mean/y_std такие, что intercept = −14 уводит базу в минус:
    # (−14)·500 + 6800 = −200.
    res = compute_negative_baseline(
        intercept_samples=_samples(-14.0, sd=0.2),
        control_betas_samples=np.zeros((0, 500)),
        x_control_norm=np.zeros((30, 0)),
        y_mean=6800.0, y_std=500.0,
    )
    assert res is not None
    assert res['prob_negative'] > 0.8, res['prob_negative']
    assert res['verdict'] == 'fail'
    assert res['baseline_mean'] < 0


def test_пограничный_случай_попадает_в_смотреть():
    """База около нуля → «смотреть», а не «годно» и не «провал»."""
    # intercept ≈ −1,0 → база ≈ 5000 − 5000 = 0, половина выборок ниже нуля.
    res = compute_negative_baseline(
        intercept_samples=_samples(-1.0, sd=0.05, seed=3),
        control_betas_samples=np.zeros((0, 500)),
        x_control_norm=np.zeros((30, 0)),
        y_mean=5000.0, y_std=5000.0,
    )
    assert res is not None
    assert 0.2 <= res['prob_negative'] <= 0.8, res['prob_negative']
    assert res['verdict'] == 'watch'


def test_контроли_учитываются_а_не_игнорируются():
    """Отрицательный контроль (конкурент) двигает базу — мутация «обнулить вклад
    контролей» красит тест."""
    n_draws, T = 400, 24
    rng = np.random.RandomState(7)
    x_norm = rng.normal(0, 1, (T, 1))
    # Сильный отрицательный коэффициент: база уезжает вниз в периоды высокой
    # активности конкурента.
    betas = np.full((1, n_draws), -8.0)
    без = compute_negative_baseline(
        _samples(-0.5, n_draws), np.zeros((0, n_draws)), np.zeros((T, 0)), 6800.0, 500.0)
    с = compute_negative_baseline(
        _samples(-0.5, n_draws), betas, x_norm, 6800.0, 500.0)
    assert без is not None and с is not None
    assert с['share_periods_negative'] > без['share_periods_negative'], (
        'вклад контролей не доехал до расчёта — база не шевельнулась'
    )


def test_режим_ols_и_битый_вход_дают_молчание():
    """Нет выборок или вырожденный масштаб → None, а не выдуманное число.

    В OLS апостериорных выборок нет вовсе (`ols_modeler` их не пишет), и это
    единственный честный ответ: проверка недоступна, а не «пройдена».
    """
    assert compute_negative_baseline(np.array([]), None, None, 6800.0, 500.0) is None
    assert compute_negative_baseline(_samples(-0.5), None, None, 6800.0, 0.0) is None
    assert compute_negative_baseline(_samples(-0.5), None, None, float('nan'), 500.0) is None
    assert compute_negative_baseline(None, None, None, 6800.0, 500.0) is None


def test_пороги_объявлены_в_ответе():
    """Читатель не должен угадывать границы — они едут вместе с числом.

    Пороги 0,2/0,8 — продуктовое соглашение плана, не канон первоисточников;
    поэтому они и записаны явно, а не зашиты в чужой словарь.
    """
    res = compute_negative_baseline(
        _samples(-0.5), None, None, 5000.0, 5000.0)
    assert res['thresholds'] == {'ok_below': 0.2, 'fail_above': 0.8}
    assert res['basis'] == 'baseline_before_factor_breakout_mean'


# ── Обратная совместимость: пересчёт оценки качества ────────────────────────

def test_пересчёт_оценки_качества_сохраняет_новый_ключ(tmp_path):
    """`recompute_mqs` сливает секции, а не перезаписывает файл целиком.

    Мутация «заменить diag на new_diag целиком» красит этот тест: ключ проверки
    канона исчез бы у всех проектов при первой же миграции, причём молча.
    """
    import tools.recompute_mqs as rm  # noqa: PLC0415

    diag = {
        'mqs': {'score': 70, 'tier_label': 'Хорошее', 'components': {}},
        'verdict': 'reliable',
        'metrics': {'r_squared': 0.8, 'mape_pct': 9.0, 'n_observations': 60, 'n_parameters': 12},
        'checks': {'ratio': True},
        'negative_baseline': {'prob_negative': 0.03, 'verdict': 'ok'},
        'sensitivity_tornado': {'parameters': []},
    }
    # Повторяем ровно ту последовательность, которой пользуется инструмент.
    new_diag = {
        'mqs': {'score': 55, 'tier_label': 'Среднее', 'components': {}},
        'verdict': 'uncertain',
        'metrics': {'effective_params': 8.0},
        'checks': {'ratio': False},
    }
    diag['mqs'] = new_diag['mqs']
    diag['verdict'] = new_diag['verdict']
    diag.setdefault('metrics', {}).update(new_diag['metrics'])
    diag['checks'] = new_diag['checks']

    assert 'negative_baseline' in diag, 'ключ проверки канона потерян при пересчёте'
    assert diag['negative_baseline']['verdict'] == 'ok'
    assert 'sensitivity_tornado' in diag, 'соседний ключ верхнего уровня тоже обязан выжить'
    # Исходный код инструмента сверяем на месте: если слияние заменят на
    # присваивание, тест выше останется зелёным, а продукт сломается.
    src = Path(rm.__file__).read_text(encoding='utf-8')
    assert "diag['mqs'] = new_diag['mqs']" in src
    assert 'diag = new_diag' not in src, (
        'пересчёт стал перезаписывать диагностику целиком — ключи верхнего уровня '
        'исчезнут у всех проектов'
    )


def test_вердикт_надёжности_не_изменился_от_нового_ключа():
    """Решение владельца 2026-08-03: гейт советов по бюджету НЕ трогаем.

    Проверка канона считается и показывается, но на вердикт не влияет — иначе
    советы отключились бы там, где вчера работали (тот же класс, что блокировка
    кнопки в P0.3). Тест стережёт это решение: добавление ключа не меняет ни
    вердикт, ни отказ, ни причины — ни на слово.
    """
    from utils.optimizer_honesty import model_reliability_verdict  # noqa: PLC0415

    base = {
        'engine': 'bayesian',
        'metrics': {'r_hat_max': 1.01, 'divergences': 0, 'ratio': 5.0,
                    'chains': 4, 'draws': 2000},
        'checks': {'ratio': True},
        'mqs': {'tier': 'good', 'tier_label': 'Хорошее', 'score': 72},
    }
    было = model_reliability_verdict(dict(base))
    стало = model_reliability_verdict({
        **base,
        'negative_baseline': {'prob_negative': 0.95, 'verdict': 'fail'},
    })
    assert было == стало, 'новый ключ повлиял на гейт советов — это решение владельца, не побочный эффект'


def test_незнакомые_ключи_не_считаются_провалом():
    """Отсутствие ключа ≠ провал: старые проекты не должны «портиться».

    Диагностика модели, обученной до P0.6, ключа не содержит вовсе. Вердикт
    обязан читаться так же, как читался.
    """
    from utils.optimizer_honesty import model_reliability_verdict  # noqa: PLC0415

    старый = {
        'engine': 'bayesian',
        'metrics': {'r_hat_max': 1.005, 'divergences': 0, 'ratio': 6.0,
                    'chains': 4, 'draws': 2000},
        'checks': {'ratio': True},
        'mqs': {'tier': 'excellent', 'tier_label': 'Отличное', 'score': 88},
    }
    res = model_reliability_verdict(старый)
    assert res['verdict'] == 'reliable'
    assert res['refused'] is False


def test_ключ_переживает_запись_и_чтение_диагностики(tmp_path):
    """Санитайзер и JSON-обход не съедают новый ключ (`sanitize_nonfinite`)."""
    from utils.safe_io import sanitize_nonfinite  # noqa: PLC0415

    diag = {
        'negative_baseline': compute_negative_baseline(
            _samples(-0.5), None, None, 5000.0, 5000.0),
    }
    path = tmp_path / 'model-diagnostics.json'
    path.write_text(json.dumps(sanitize_nonfinite(diag), ensure_ascii=False), encoding='utf-8')
    back = json.loads(path.read_text(encoding='utf-8'))
    assert back['negative_baseline']['verdict'] == 'ok'
    assert back['negative_baseline']['thresholds']['fail_above'] == 0.8


# ── Находки внешнего аудита блока P0.6 (2026-08-03) ─────────────────────────

def test_один_испорченный_отсчёт_не_гасит_проверку():
    """Medium: фильтр непригодных значений резал ПЕРИОДЫ, а не отсчёты.

    `isfinite(...).all(axis=1)` — свёртка по отсчётам, поэтому единственный NaN
    среди тысяч выборок делал непригодной каждую строку, и функция возвращала
    None: один испорченный отсчёт гасил всю проверку, а на экране это выглядело
    как «проверка недоступна».
    """
    ic = _samples(-0.5)
    ic[7] = np.nan
    res = compute_negative_baseline(ic, None, None, 5000.0, 5000.0)
    assert res is not None, 'один NaN снова гасит всю проверку'
    assert res['n_draws'] == 499, 'отброшен должен быть ровно один отсчёт'


def test_несогласованные_формы_контролей_помечаются():
    """Medium: раньше вклад контролей выпадал МОЛЧА.

    База считалась по одному свободному члену, а результат отдавался как
    полноценный — читатель диагностики не мог отличить «контроли учтены» от
    «контроли выброшены».
    """
    betas = np.full((3, 500), -1.0)
    x_norm = np.zeros((30, 2))  # 2 колонки против 3 наборов коэффициентов
    res = compute_negative_baseline(_samples(-0.5), betas, x_norm, 5000.0, 5000.0)
    assert res is not None
    assert res['controls_dropped'] is True, 'выпадение контролей снова молчит'
    # А когда всё сошлось — признак опущен.
    ok = compute_negative_baseline(
        _samples(-0.5), np.full((2, 500), -1.0), np.zeros((30, 2)), 5000.0, 5000.0)
    assert ok['controls_dropped'] is False


def test_убыточный_денежный_kpi_не_объявляется_провалом():
    """Medium: при среднем KPI ниже нуля отрицательная база НОРМАЛЬНА.

    Денежная метрика «прибыль» у убыточного проекта: проверка объявляла `fail`
    и показывала клиенту «без рекламы продаж не было бы вовсе — вклад каналов
    завышен». Утверждение ложное, вклад каналов тут ни при чём.
    """
    assert compute_negative_baseline(_samples(-0.5), None, None, -2000.0, 500.0) is None
    assert compute_negative_baseline(_samples(-0.5), None, None, 0.0, 500.0) is None


def test_вырожденная_выборка_не_даёт_псевдооценки():
    """Low: на одном-двух отсчётах вероятность равна ровно 0 или 1."""
    assert compute_negative_baseline(_samples(-0.5, n=1), None, None, 5000.0, 5000.0) is None
    assert compute_negative_baseline(_samples(-0.5, n=9), None, None, 5000.0, 5000.0) is None
    assert compute_negative_baseline(_samples(-0.5, n=10), None, None, 5000.0, 5000.0) is not None


def test_основание_расчёта_названо_честно():
    """Low: `displayed_baseline_mean` утверждал равенство с полосой на экране.

    Декомпозиция вычитает из базы каждый выносимый фактор любого знака, поэтому
    при наличии хотя бы одного фактора числа расходятся всегда.
    """
    res = compute_negative_baseline(_samples(-0.5), None, None, 5000.0, 5000.0)
    assert res['basis'] == 'baseline_before_factor_breakout_mean'
