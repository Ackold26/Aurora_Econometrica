"""Aurora Econometrica — воспроизводимость расчёта (P0.2).

Зерно генератора случайных чисел для MCMC + снимок среды, от которой
результат зависит помимо зерна.

Зачем
-----
MCMC-сэмплер стохастичен. Без зерна два обучения на одних и тех же данных
дают разные апостериорные интервалы: клиент пересчитывает модель и видит,
что цифры поехали. Стандарт IAB (дек. 2025) требует воспроизводимости
расчёта как условия приёмки MMM.

Границы обещания
----------------
Зерно даёт повторяемость **на той же среде**. Битовое совпадение между
машинами не гарантируется и обещать его нельзя: результат зависит ещё и от
того, какой ярус сэмплера фактически сработал, каким методом разложены
цепи и сколько устройств увидел JAX. Поэтому вместе с зерном сохраняется
снимок среды — без него «то же зерно, другой ответ» выглядит как дефект,
хотя это смена яруса.

Почему зерно передаётся ЯВНО, а не через ``np.random.seed()``
-------------------------------------------------------------
В движке уже есть засеянные пути со СВОИМИ генераторами:
``utils/reliability_a4.py`` (проверка приоров), ``utils/conformal.py``,
``utils/ols_bootstrap.py`` — у всех ``np.random.default_rng(42)``,
независимый поток. Глобальный засев сдвинул бы их выдачу, а значит и уже
выпущенные клиентам интервалы. Явный ``random_seed=`` в ``pm.sample``
их не касается: проверено зондом — глобального ``np.random.seed`` в движке
нет ни одного.
"""
from __future__ import annotations

import logging
import os
import platform
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Зерно по умолчанию. 42 — уже фактический дефолт остальных засеянных путей
# движка (reliability_a4, conformal, ols_bootstrap); один и тот же номер
# держим ради единообразия, а не ради свойств числа.
DEFAULT_SEED = 42

# Переменная среды для разового переопределения (диагностика, прогон
# детерминизма в тестах). Конфиг проекта имеет приоритет над ней:
# у проекта зерно — часть паспорта расчёта, у среды — временная мера.
SEED_ENV_VAR = 'AURORA_MCMC_SEED'

# Ярусы сэмплера. Обучение идёт по цепочке: Tier-1 → Tier-2 → отказ.
# Ярус ОБЯЗАН попасть в снимок: при одном зерне разные ярусы дают разные
# числа, а откат на запасной происходит молча (ловится только по журналу).
TIER_NUMPYRO = 'numpyro-nuts'
TIER_PYTENSOR = 'pytensor-nuts'
TIER_PYTENSOR_NO_CALLBACK = 'pytensor-nuts-no-callback'


def resolve_seed(config: dict[str, Any] | None = None) -> tuple[int, str]:
    """Зерно расчёта и источник, откуда оно взято.

    Порядок: ``config['seed']`` → переменная среды → ``DEFAULT_SEED``.

    Явный источник нужен для паспорта расчёта: «зерно 42» само по себе не
    отличает заданное пользователем от подставленного по умолчанию, а для
    старых моделей (ключа в конфиге нет вовсе) это разные ситуации.

    Args:
        config: конфиг обучения. ``None`` и отсутствие ключа равнозначны.

    Returns:
        (зерно, источник) — источник один из ``'config'``, ``'env'``,
        ``'default'``.
    """
    raw = (config or {}).get('seed')
    if raw is not None:
        seed = _coerce_seed(raw, origin='config')
        if seed is not None:
            return seed, 'config'

    raw_env = os.environ.get(SEED_ENV_VAR)
    if raw_env not in (None, ''):
        seed = _coerce_seed(raw_env, origin=f'env {SEED_ENV_VAR}')
        if seed is not None:
            return seed, 'env'

    return DEFAULT_SEED, 'default'


def _coerce_seed(raw: Any, *, origin: str) -> int | None:
    """Привести значение к неотрицательному int либо отвергнуть с журналом.

    Молча падать на дефолт нельзя: пользователь, задавший зерно с опечаткой,
    получил бы «воспроизводимо, но не тем зерном, что просил».
    """
    try:
        seed = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            f'Зерно из {origin} не число ({raw!r}) — беру значение по умолчанию '
            f'{DEFAULT_SEED}.'
        )
        return None
    if seed < 0:
        logger.warning(
            f'Зерно из {origin} отрицательное ({seed}) — беру значение по умолчанию '
            f'{DEFAULT_SEED}.'
        )
        return None
    return seed


def environment_snapshot(
    *,
    seed: int,
    seed_source: str,
    chains: int,
    draws: int,
    tune: int,
    has_compiler: bool,
    chain_method: str | None = None,
    jax_devices: int | None = None,
    data_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Снимок среды, от которой результат зависит помимо зерна.

    Ярус сэмплера здесь ещё не известен — он определяется по факту
    сэмплирования и дописывается ``mark_sampler_tier``. Пустое поле
    ``sampler_tier`` в сохранённом снимке означает, что обучение до
    сэмплинга не дошло.

    Args:
        seed: зерно, фактически переданное сэмплеру.
        seed_source: источник зерна из ``resolve_seed``.
        chains, draws, tune: параметры MCMC.
        has_compiler: наличие C-компилятора. Влияет на скорость Tier-2 и на
            дефолтные параметры MCMC, а через них — на результат.
        chain_method: способ раскладки цепей, запрошенный движком.
        jax_devices: сколько устройств увидел JAX — именно от этого числа
            движок выбирает раскладку.
        data_fingerprint: отпечаток исходных данных из
            ``utils.data_fingerprint.build_data_fingerprint`` — чем именно
            кормили модель. Снимается при обучении: к моменту выпуска
            документа исходного файла на месте может уже не быть.
            ``None`` у моделей, обученных до появления поля, и у вызовов, где
            данных нет (проверки среды) — отсутствие отпечатка так и
            записывается отсутствием, подставлять вместо него нечего.
    """
    return {
        'seed': seed,
        'seed_source': seed_source,
        'sampler_tier': None,
        'chain_method_requested': chain_method,
        # Доехала ли запрошенная раскладка до сэмплера. Ярус PyTensor цепи
        # так не раскладывает вовсе — там поле остаётся ложью по факту, а не
        # по недосмотру. История поля: до 2026-08-03 раскладка передавалась
        # прямым аргументом `pm.sample(chain_method=...)`, который PyMC 5.28
        # молча проглатывает; поле и заведено, чтобы паспорт не выдавал
        # запрошенное за применённое.
        'chain_method_delivered': False,
        'jax_devices': jax_devices,
        # Отпечаток исходных данных: содержимое таблицы + байты файла.
        # Обе половины со своим статусом — они отказывают независимо.
        'data_fingerprint': data_fingerprint,
        'has_compiler': has_compiler,
        'mcmc': {'chains': chains, 'draws': draws, 'tune': tune},
        'versions': _package_versions(),
        'platform': {
            'system': platform.system(),
            'release': platform.release(),
            'machine': platform.machine(),
            'python': platform.python_version(),
        },
    }


def seed_from_model(model_data: dict[str, Any] | None) -> tuple[int, str]:
    """Зерно, которым обучалась сохранённая модель.

    Нужно перепроверке на истории: она переобучает модель на урезанных
    окнах и обязана делать это тем же зерном, иначе разброс между
    прогонами проверки смешается с разбросом самой модели.

    Порядок: снимок воспроизводимости в модели → конфиг модели → общий
    разбор (переменная среды, затем значение по умолчанию).

    У моделей, обученных до P0.2, снимка нет и зерна не было вовсе —
    они получают значение по умолчанию. Совпадения с их исходным
    обучением это не даёт и дать не может; даёт повторяемость самой
    перепроверки, что и требуется от неё.

    Returns:
        (зерно, источник) — источник дополнительно к значениям
        ``resolve_seed`` может быть ``'model'``.
    """
    snapshot = (model_data or {}).get('reproducibility')
    if isinstance(snapshot, dict) and snapshot.get('seed') is not None:
        seed = _coerce_seed(snapshot['seed'], origin='снимок модели')
        if seed is not None:
            return seed, 'model'
    return resolve_seed((model_data or {}).get('config'))


def mark_chain_layout(
    snapshot: dict[str, Any] | None,
    *,
    chain_method: str,
    jax_devices: int,
) -> None:
    """Записать в снимок раскладку цепей и число устройств.

    Отдельно от ``environment_snapshot``, потому что раскладка выбирается
    позже — уже внутри блока сэмплирования, по числу видимых устройств.

    Вызывается только на ярусе NumPyro и только там, где раскладка
    действительно передана сэмплеру через ``nuts_sampler_kwargs``, — потому
    и выставляет ``chain_method_delivered``.

    ⚠️ Доставлена ≠ применена буквально: NumPyro сам понижает ``parallel``
    до ``sequential``, если устройств меньше, чем цепей. На числа это не
    влияет — ``parallel`` и ``sequential`` дают побитово одинаковый
    результат при одном зерне (проверено зондом 2026-08-03).
    """
    if snapshot is None:
        return
    snapshot['chain_method_requested'] = chain_method
    snapshot['chain_method_delivered'] = True
    snapshot['jax_devices'] = jax_devices


def mark_sampler_tier(snapshot: dict[str, Any] | None, tier: str) -> None:
    """Записать в снимок ярус, который сработал на самом деле.

    Вызывать сразу после успешного возврата сэмплера, а не при входе в
    ветку: ветка Tier-1 может начаться и упасть на запасной путь.
    """
    if snapshot is None:
        return
    snapshot['sampler_tier'] = tier


def _package_versions() -> dict[str, str | None]:
    """Версии пакетов, влияющих на числа. Отсутствующий пакет → ``None``.

    Импорт здесь ленивый и защищённый: снимок среды не имеет права уронить
    обучение из-за отсутствующего необязательного пакета (jax/numpyro в
    медленной поставке может не быть вовсе).
    """
    versions: dict[str, str | None] = {
        'python': sys.version.split()[0],
    }
    for name in ('numpy', 'pymc', 'pytensor', 'numpyro', 'jax'):
        versions[name] = _version_of(name)
    return versions


def _version_of(module_name: str) -> str | None:
    try:
        module = __import__(module_name)
    except Exception:  # noqa: BLE001 — любой сбой импорта = пакета нет
        return None
    return getattr(module, '__version__', None)
