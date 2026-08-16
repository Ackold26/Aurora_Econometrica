"""Aurora Econometrica – критерий совпадения двух расчётов (допуск воспроизведения).

Зачем
-----
Паспорт воспроизводимости отвечает на вопрос «как повторить расчёт»: зерно,
настройки сэмплера, версии библиотек, отпечаток данных. Он НЕ отвечает на
вопрос «какое расхождение двух повторов считается совпадением», а без ответа
спор о результате неразрешим: апостериорная оценка – случайная процедура,
повторный прогон с другим зерном даёт другие числа, и любая сторона вправе
назвать любое расхождение несовпадением.

Модуль объявляет проверяемый критерий и применяет его к двум сохранённым
моделям, выдавая разбор по каналам и по величинам.

Что сверяется
-------------
Только то, что клиент видит и на чём принимает решения:

* окупаемость канала и доля канала во вкладе медиа – из разбивки продаж;
* коэффициент канала, скорость переноса, форма и точка насыщения – из модели.

Внутренние величины сэмплера (шаг, длина траектории, служебные преобразования)
не сверяются намеренно: их расхождение ничего не говорит о том, изменится ли
совет по бюджету.

Первые две величины в паспорте не приводятся и приводиться не могут: они не
параметры модели, а результат разбивки продаж. Поэтому критерий называет их
адрес прямо – отчёт по модели, раздел разбивки, – и прямо же говорит, что при
сверке ТОЛЬКО по паспорту они остаются непроверенными (замечание Б-1 внешнего
аналитика, 2026-08-16: молчание об этом делало треть приёмочных требований
невыполнимой по построению, и посторонний узнавал об этом сам, посреди работы).

Три режима и откуда взялись числа
---------------------------------
Режим определяется по двум паспортам автоматически, а не выбирается на глаз:
сторона, недовольная результатом, не должна иметь возможности подобрать себе
допуск пошире.

1. **Повторный запуск той же программой в той же среде** – совпали зерно,
   версии библиотек, вид сэмплера, число цепей и выборок, платформа. Допуск
   нулевой.
   Замер 2026-08-16: два прогона с зерном 42 на одной машине дали ПОБИТОВО
   равные апостериорные выборки (media_betas, alphas, gammas, intercept,
   adstock_decay, control_betas; 8000 выборок на канал; максимум модуля
   разности 0,0) и, как следствие, равные до последнего печатаемого знака
   окупаемость, вклад и параметры каналов. Поэтому допуск здесь не
   «маленький», а именно нулевой: любое расхождение означает, что различие
   где-то ещё, и его надо искать, а не списывать на случайность метода.

   🔴 Эта ветвь СТОРОННЕМУ ПРОВЕРЯЮЩЕМУ НЕПРИМЕНИМА, и называть её самой
   строгой – ошибка (замечание С-3, 2026-08-16). Посторонний аналитик
   воспроизвёл всё, что ветвь объявляет условием, – зерно 42, версии всех шести
   библиотек, машину, число цепей, выборок и прогрева, target_accept, раскладку
   цепей, – и точного совпадения не получил, потому что получить его не мог:
   побитовое повторение определяется не зерном и средой, а ИДЕНТИЧНОСТЬЮ КОДА –
   порядком объявления переменных в графе модели и реализацией свёртки переноса.
   То есть ветвь описывает повторный запуск программы самой себя, самую слабую
   форму воспроизводимости, и в документе для стороннего занимала место самой
   строгой. Ветвь оставлена: ею проверяется наш собственный детерминизм, и
   побитовое совпадение выше – именно её подтверждение. Для сторонней проверки
   действует ветвь 2 либо 3.

2. **Другое зерно при полном расчёте** – среда и настройки те же, зёрна разные,
   в каждом расчёте не менее ПОЛНЫЙ_РАСЧЁТ итоговых выборок.
   Замер 2026-08-16, проект с 31 наблюдением и 4 каналами, зёрна 42 / 7 / 123,
   4 цепи × 2000 выборок (три пары): окупаемость расходилась не более чем на
   2,4 %, коэффициент канала – 2,2 %, скорость переноса – 2,1 %, точка
   насыщения – 1,7 %, форма насыщения – 1,4 %, доля канала во вкладе –
   0,7 процентного пункта.

3. **Сокращённый расчёт, другая среда или другие настройки** – всё остальное:
   меньше выборок, другое число цепей, другие версии библиотек, другая машина.
   Замер 2026-08-16: при 500 выборках на цепь вместо 2000 расхождение по
   другому зерну доходило до 3,5 % по окупаемости, 3,4 % по коэффициенту и
   переносу, 0,6 процентного пункта по доле вклада; при том же зерне, но
   укороченной цепи – до 3,0 % по окупаемости. Расхождение между разными
   МАШИНАМИ и сборками библиотек мы не мерили (второй машины с иной сборкой
   нет), поэтому оно отнесено сюда же – к самому широкому допуску, а не
   объявлено измеренным.

Допуски объявлены с запасом к измеренному максимуму примерно вдвое: замер снят
на одном проекте, а критерий действует на всех.

Какая ветвь применима к предъявленному расчёту – считает паспорт, не читатель
-----------------------------------------------------------------------------
Критерий вводит понятие полного расчёта (от ПОЛНЫЙ_РАСЧЁТ итоговых выборок), а
паспорт может описывать расчёт короче: машина без компилятора считает 2 цепи по
1000, а быстрый прогон – и того меньше. Пока критерий молчал об этом, читатель
брал ветвь 2 (строгий допуск) и получал ЛОЖНОЕ «не совпало»: замер 2026-08-16
показал, что при 300 выборках два прогона ОДНОГО И ТОГО ЖЕ стороннего кода,
отличающиеся только зерном, расходятся на 5,79 % по коэффициенту и 7,42 % по
переносу – то есть допуск ветви 2 недостижим даже для программы, сверяющейся
сама с собой (замечание С-2).

Поэтому применимую ветвь определяет и печатает сам паспорт – по числу итоговых
выборок из своего же раздела прогона (`applicable_mode`). Выбирать её на глаз
читателю не предлагается, а ветвь 1 в применимые не попадает никогда: она
описывает нашу собственную проверку детерминизма, а не стороннюю сверку.

Вторая опора критерия – собственный разброс модели
--------------------------------------------------
Процентный допуск, откалиброванный на одном проекте, плохо переносится на
канал с малой долей бюджета: у него шире апостериорный разброс, и относительное
расхождение прогонов там законно больше. Поэтому величина считается совпавшей
также тогда, когда расхождение не превышает ДОЛЯ_ДИАПАЗОНА ширины
правдоподобного диапазона этой же величины: сдвиг внутри четверти собственного
разброса модели не меняет ни одного вывода, который по этому числу делается.

Замер 2026-08-16: по всем каналам и всем сценариям расхождение окупаемости
составило не более 1,6 % ширины её правдоподобного диапазона – то есть
случайность метода на два порядка мельче той неопределённости, которую мы и
так показываем клиенту.

Границы критерия – в конце файла, отдельным разделом.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Версия правил. Входит в отчёт сверки и в сертификат: изменение допусков
# обязано менять и метку, иначе два разных критерия окажутся под одним именем,
# и прежнее заключение станет невозможно прочитать правильно.
#
# v2 (2026-08-16): сами допуски не двигались – изменились имена ветвей и состав
# объявления. Метку это меняет по той же причине: заключение v1 ссылается на
# ветвь «то же зерно, та же среда и те же настройки», которой под этим именем
# больше нет, и в v1 нет ни применимой ветви, ни адреса величин из разбивки.
# Читатель обязан видеть, какой редакцией критерия вынесено заключение.
CRITERION_VERSION = 'aurora-repro-tolerance-v2'

MODE_EXACT = 'exact'
MODE_STRICT = 'other_seed_full'
MODE_WIDE = 'reduced_or_other_env'

MODE_TITLES = {
    # Имя ветви 1 говорит, ЧТО она на самом деле проверяет: тот же код запускает
    # сам себя. Прежнее имя («то же зерно, та же среда и те же настройки»)
    # перечисляло условия, выполнимые для постороннего, и обещало ему точное
    # совпадение, недостижимое в принципе (замечание С-3, 2026-08-16).
    MODE_EXACT: 'повторный запуск той же программой в той же среде',
    MODE_STRICT: 'другое зерно при полном расчёте',
    MODE_WIDE: 'сокращённый расчёт, другая среда или другие настройки',
}

# Почему ветвь 1 не годится стороннему – одним предложением, для клиента.
SELF_RERUN_NOTE = (
    'Стороннему проверяющему эта ветвь неприменима: побитовое совпадение даёт не '
    'зерно и среда, а тот же самый код – порядок объявления переменных модели и '
    'реализация переноса. Ею проверяется наш собственный детерминизм; для '
    'сторонней проверки действует ветвь по другому зерну либо по сокращённому '
    'расчёту.'
)

# Где посторонний берёт две величины, которых в паспорте нет и быть не может.
DECOMPOSITION_QUANTITIES_SOURCE = (
    'окупаемость канала и доля канала во вкладе медиа в паспорт не входят: это не '
    'параметры модели, а результат разбивки продаж. Они приводятся в отчёте по '
    'модели – раздел «Декомпозиция», таблица «Портфель каналов»; в программе – '
    'вкладка результатов «Окупаемость каналов»'
)

# Прямая оговорка о том, чего сверка по одному паспорту не даёт.
DECOMPOSITION_UNVERIFIED_NOTE = (
    'При сверке только по паспорту эти две величины остаются непроверенными: в '
    'паспорте их нет, и подтвердить их можно лишь по отчёту с разбивкой продаж.'
)

# Порог полного расчёта: число итоговых выборок (цепи × выборки), начиная с
# которого действует строгий допуск. 8000 – настройка по умолчанию при наличии
# компилятора (4 цепи × 2000). Машина без компилятора считает 2 цепи × 1000 и
# попадает в широкий допуск честно, а не по недосмотру.
FULL_RUN_DRAWS = 8000

# Сверяемые величины: ключ → (клиентское имя, вид сравнения).
# 'relative' – расхождение в процентах от значения первого расчёта;
# 'points'   – расхождение в процентных пунктах (величина сама уже доля).
QUANTITIES: dict[str, tuple[str, str]] = {
    'roi': ('окупаемость канала', 'relative'),
    'contribution_pct': ('доля канала во вкладе медиа', 'points'),
    'beta': ('коэффициент канала', 'relative'),
    'decay': ('скорость переноса', 'relative'),
    'alpha': ('форма насыщения', 'relative'),
    'gamma': ('точка насыщения', 'relative'),
}

# Величины, которые даёт разбивка продаж (нужен доступ к исходным данным).
# Остальные лежат в самой модели и сверяются всегда.
QUANTITIES_FROM_DECOMPOSITION = ('roi', 'contribution_pct')

# Допуски по режимам: проценты для 'relative', процентные пункты для 'points'.
# Обоснование каждого числа – в шапке файла.
TOLERANCES: dict[str, dict[str, float]] = {
    MODE_EXACT: {
        'roi': 0.0,
        'contribution_pct': 0.0,
        'beta': 0.0,
        'decay': 0.0,
        'alpha': 0.0,
        'gamma': 0.0,
    },
    MODE_STRICT: {
        'roi': 5.0,
        'contribution_pct': 1.5,
        'beta': 5.0,
        'decay': 5.0,
        'alpha': 5.0,
        'gamma': 5.0,
    },
    MODE_WIDE: {
        'roi': 10.0,
        'contribution_pct': 3.0,
        'beta': 10.0,
        'decay': 10.0,
        'alpha': 10.0,
        'gamma': 10.0,
    },
}

# Вторая опора: доля ширины правдоподобного диапазона, внутри которой
# расхождение считается несущественным независимо от процентов.
CI_SHARE_LIMIT_PCT = 25.0

# Величины, у которых в разбивке есть границы правдоподобного диапазона.
CI_BOUNDS = {
    'roi': ('roi_ci_low', 'roi_ci_high'),
}

# Поля паспорта, совпадение которых означает «та же среда». Вид сэмплера здесь
# не формальность: переход numpyro → pymc меняет числа при том же зерне.
ENV_FIELDS = ('sampler_tier', 'platform', 'has_compiler')


class NotComparable(Exception):
    """Расчёты сверять нельзя: разные данные, разные каналы или разный показатель."""


# ── Снятие величин с одного расчёта ──────────────────────────────────────────

def read_run(model_path: str | Path, project_dir: str | Path | None = None) -> dict[str, Any]:
    """Снять с одного расчёта всё, что нужно для сверки.

    Args:
        model_path: файл модели (`latest.aurora-model` либо `latest.pkl`).
        project_dir: каталог проекта – нужен разбивке продаж за окупаемостью и
            вкладом. По умолчанию берётся каталог на два уровня выше файла
            модели (`<проект>/models/latest...`).

    Returns:
        {'passport', 'config', 'channels', 'decomposition_available',
         'decomposition_reason', 'model_path', 'project_dir'}

    Величины из модели снимаются всегда; окупаемость и вклад – только если
    разбивка построилась. Отсутствие разбивки НЕ подменяется ничем: сверка
    честно объявит эти величины несверявшимися.
    """
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f'Файл модели не найден: {path}')

    project = Path(project_dir) if project_dir else path.parent.parent

    from engines.persistence import load_model_with_compat
    model_data = load_model_with_compat(path)

    config = model_data.get('config') or {}
    passport = model_data.get('reproducibility')
    if not isinstance(passport, dict):
        passport = {}

    channels: dict[str, dict[str, Any]] = {}
    for name, params in (model_data.get('channel_params') or {}).items():
        channels[name] = {
            'beta': params.get('beta'),
            'alpha': params.get('alpha'),
            'gamma': params.get('gamma'),
            'decay': params.get('decay'),
        }

    decomposition_available = False
    decomposition_reason: str | None = None
    try:
        from engines.decomposer import decompose
        result = decompose(str(project), model_path=str(path), save_results=False)
        if result.get('status') == 'error':
            decomposition_reason = str(result.get('message') or result.get('error_code'))
        else:
            for ch in result.get('channels') or []:
                name = ch.get('name') or ch.get('channel')
                row = channels.setdefault(name, {})
                row['roi'] = ch.get('roi')
                row['contribution_pct'] = ch.get('contribution_pct')
                row['roi_ci_low'] = ch.get('roi_ci_low')
                row['roi_ci_high'] = ch.get('roi_ci_high')
            decomposition_available = True
    except Exception as err:  # noqa: BLE001 – сверка не обязана падать из-за разбивки
        decomposition_reason = f'{type(err).__name__}: {err}'
        logger.warning('Разбивка продаж при сверке расчётов не построена: %s', decomposition_reason)

    return {
        'model_path': str(path),
        'project_dir': str(project),
        'passport': passport,
        'config': config,
        'channels': channels,
        'decomposition_available': decomposition_available,
        'decomposition_reason': decomposition_reason,
    }


# ── Определение режима сверки ────────────────────────────────────────────────

def _sampler_settings(passport: dict[str, Any]) -> dict[str, Any]:
    mcmc = passport.get('mcmc')
    return dict(mcmc) if isinstance(mcmc, dict) else {}


def _versions(passport: dict[str, Any]) -> dict[str, Any]:
    versions = passport.get('versions')
    return dict(versions) if isinstance(versions, dict) else {}


def total_draws(passport: dict[str, Any]) -> int | None:
    """Число итоговых выборок расчёта: цепи × выборки. None, если не записано."""
    mcmc = _sampler_settings(passport)
    chains, draws = mcmc.get('chains'), mcmc.get('draws')
    try:
        if chains is None or draws is None:
            return None
        return int(chains) * int(draws)
    except (TypeError, ValueError):
        return None


def applicable_mode(passport: dict[str, Any] | None) -> tuple[str, str]:
    """Ветвь допусков, применимая к сторонней проверке ЭТОГО расчёта.

    Считается по числу итоговых выборок из раздела прогона самого паспорта –
    читателю выбирать не предлагается. Ветвь «повторный запуск той же
    программой» здесь не возвращается никогда: стороннему она недоступна
    (см. SELF_RERUN_NOTE).

    Args:
        passport: паспорт прогона – раздел `reproducibility` модели либо его
            выжимка в сертификате. Годится и неполный: чего нет, то и будет
            названо отсутствующим.

    Returns:
        (режим, объяснение по-русски – печатается клиенту)
    """
    draws = total_draws(passport or {})
    if draws is None:
        return MODE_WIDE, (
            'В паспорте не записано число итоговых выборок, поэтому полнота '
            'расчёта не подтверждена и применяется самый широкий допуск.'
        )
    if draws < FULL_RUN_DRAWS:
        return MODE_WIDE, (
            f'Расчёт сокращённый: {draws} итоговых выборок, а полным считается '
            f'расчёт от {FULL_RUN_DRAWS}. Чем короче расчёт, тем шире собственный '
            f'разброс метода, поэтому и допуск шире.'
        )
    return MODE_STRICT, (
        f'Расчёт полный: {draws} итоговых выборок при пороге полноты в '
        f'{FULL_RUN_DRAWS}.'
    )


def detect_mode(run_a: dict[str, Any], run_b: dict[str, Any]) -> tuple[str, str]:
    """Определить режим сверки по двум паспортам.

    Returns:
        (режим, объяснение по-русски – печатается в заключении)
    """
    pa, pb = run_a.get('passport') or {}, run_b.get('passport') or {}
    seed_a, seed_b = pa.get('seed'), pb.get('seed')

    env_same = (
        _versions(pa) == _versions(pb)
        and _sampler_settings(pa) == _sampler_settings(pb)
        and all(pa.get(field) == pb.get(field) for field in ENV_FIELDS)
    )

    if seed_a is None or seed_b is None:
        return MODE_WIDE, (
            'У одного из расчётов не записано зерно, поэтому применяется самый '
            'широкий допуск.'
        )
    if not env_same:
        return MODE_WIDE, (
            'Расчёты выполнены при разных настройках либо в разной среде: '
            'отличаются версии библиотек, вид расчёта, число цепей или выборок '
            'либо машина.'
        )
    if seed_a == seed_b:
        return MODE_EXACT, (
            f'Зерно ({seed_a}), настройки расчёта, версии библиотек и машина совпадают.'
        )

    draws_a, draws_b = total_draws(pa), total_draws(pb)
    if draws_a is None or draws_b is None:
        return MODE_WIDE, (
            f'Зёрна расчётов различаются ({seed_a} и {seed_b}), а число итоговых '
            'выборок в паспорте не записано, поэтому применяется широкий допуск.'
        )
    if min(draws_a, draws_b) < FULL_RUN_DRAWS:
        return MODE_WIDE, (
            f'Зёрна расчётов различаются ({seed_a} и {seed_b}), расчёт сокращённый: '
            f'{min(draws_a, draws_b)} итоговых выборок при полном расчёте от '
            f'{FULL_RUN_DRAWS}. Чем короче расчёт, тем шире разброс, поэтому и допуск шире.'
        )
    return MODE_STRICT, (
        f'Зёрна расчётов различаются ({seed_a} и {seed_b}); среда, настройки и '
        f'полнота расчёта ({min(draws_a, draws_b)} итоговых выборок) совпадают.'
    )


# ── Расхождение и вердикт ────────────────────────────────────────────────────

def deviation(value_a: Any, value_b: Any, kind: str) -> float | None:
    """Расхождение двух значений: проценты для 'relative', пункты для 'points'.

    None, если хотя бы одного значения нет либо относительное расхождение не
    определено (первое значение равно нулю). None означает «не сверено» и
    никогда не засчитывается как совпадение.
    """
    if value_a is None or value_b is None:
        return None
    try:
        a, b = float(value_a), float(value_b)
    except (TypeError, ValueError):
        return None
    if kind == 'points':
        return abs(a - b)
    if a == 0.0:
        return None
    return abs(a - b) / abs(a) * 100.0


def _ci_share(row_a: dict[str, Any], value_a: Any, value_b: Any, key: str) -> float | None:
    """Расхождение как доля ширины правдоподобного диапазона, в процентах."""
    bounds = CI_BOUNDS.get(key)
    if not bounds or value_a is None or value_b is None:
        return None
    low, high = row_a.get(bounds[0]), row_a.get(bounds[1])
    if low is None or high is None:
        return None
    try:
        width = float(high) - float(low)
        if width <= 0:
            return None
        return abs(float(value_a) - float(value_b)) / width * 100.0
    except (TypeError, ValueError):
        return None


def _content_hash(passport: dict[str, Any]) -> str | None:
    """Отпечаток СОДЕРЖИМОГО таблицы. Отпечаток файла здесь не годится:
    пересохранение xlsx законно меняет байты и не меняет данных."""
    fingerprint = passport.get('data_fingerprint')
    if not isinstance(fingerprint, dict):
        return None
    content = fingerprint.get('content')
    if not isinstance(content, dict):
        return None
    value = content.get('content_sha256')
    return value if isinstance(value, str) and value else None


def _check_comparable(run_a: dict[str, Any], run_b: dict[str, Any]) -> None:
    """Отказать в сверке, если расчёты сделаны не об одном и том же."""
    ca, cb = run_a.get('config') or {}, run_b.get('config') or {}
    if ca.get('kpi_column') != cb.get('kpi_column'):
        raise NotComparable(
            'Расчёты сделаны по разным целевым показателям, сверять их нельзя.'
        )
    if sorted(ca.get('media_columns') or []) != sorted(cb.get('media_columns') or []):
        raise NotComparable(
            'Наборы каналов в расчётах различаются, сверять их нельзя.'
        )
    hash_a = _content_hash(run_a.get('passport') or {})
    hash_b = _content_hash(run_b.get('passport') or {})
    if hash_a and hash_b and hash_a != hash_b:
        raise NotComparable(
            'Отпечатки исходных данных различаются: расчёты сделаны на разных '
            'таблицах, и совпадения от них ждать не следует.'
        )


def compare_runs(
    model_a: str | Path,
    model_b: str | Path,
    *,
    project_a: str | Path | None = None,
    project_b: str | Path | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Сверить два расчёта по объявленному критерию.

    Args:
        model_a, model_b: файлы сохранённых моделей.
        project_a, project_b: каталоги проектов (для разбивки продаж). По
            умолчанию выводятся из путей моделей.
        mode: принудительный режим. По умолчанию режим определяется из
            паспортов – это и есть правильный путь; ручной оставлен для проверок
            и всегда отмечается в заключении.

    Returns:
        {'status': 'compared'|'not_comparable',
         'verdict': 'match'|'mismatch'|None,
         'mode', 'mode_title', 'mode_reason', 'criterion_version',
         'tolerances', 'ci_share_limit_pct',
         'channels': [...], 'unverified': [...], 'notes': [...]}
    """
    run_a = read_run(model_a, project_a)
    run_b = read_run(model_b, project_b)

    try:
        _check_comparable(run_a, run_b)
    except NotComparable as err:
        return {
            'status': 'not_comparable',
            'verdict': None,
            'reason': str(err),
            'criterion_version': CRITERION_VERSION,
        }

    notes: list[str] = []
    detected, reason = detect_mode(run_a, run_b)
    used_mode = mode or detected
    if used_mode not in TOLERANCES:
        raise ValueError(f'Неизвестный режим сверки: {used_mode}')
    if mode and mode != detected:
        notes.append(
            f'Режим сверки задан вручную ({MODE_TITLES[used_mode]}), а по паспортам '
            f'определяется как «{MODE_TITLES[detected]}».'
        )
    limits = TOLERANCES[used_mode]

    unverified: list[str] = []
    if not (run_a['decomposition_available'] and run_b['decomposition_available']):
        unverified = list(QUANTITIES_FROM_DECOMPOSITION)
        причина = (
            run_a['decomposition_reason']
            or run_b['decomposition_reason']
            or 'причина не установлена'
        )
        notes.append(
            'Окупаемость и вклад каналов не сверялись: разбивка продаж по одному '
            f'из расчётов не построена ({причина}).'
        )

    names_a, names_b = set(run_a['channels']), set(run_b['channels'])
    only_a, only_b = sorted(names_a - names_b), sorted(names_b - names_a)
    if only_a or only_b:
        notes.append(
            'Наборы каналов в расчётах не совпали: только в первом – '
            f'{only_a or "нет"}; только во втором – {only_b or "нет"}.'
        )

    channels: list[dict[str, Any]] = []
    all_within = not (only_a or only_b)
    for name in sorted(names_a & names_b):
        row_a, row_b = run_a['channels'][name], run_b['channels'][name]
        quantities: dict[str, Any] = {}
        channel_within = True
        for key, (title, kind) in QUANTITIES.items():
            if key in unverified:
                continue
            value_a, value_b = row_a.get(key), row_b.get(key)
            dev = deviation(value_a, value_b, kind)
            limit = limits[key]
            share = _ci_share(row_a, value_a, value_b, key)
            if dev is None:
                within, passed_by = None, None
            elif dev <= limit:
                within, passed_by = True, 'допуск'
            elif limit > 0 and share is not None and share <= CI_SHARE_LIMIT_PCT:
                within, passed_by = True, 'диапазон'
            else:
                within, passed_by = False, None
            if within is False:
                channel_within = False
            quantities[key] = {
                'title': title,
                'a': value_a,
                'b': value_b,
                'deviation': dev,
                'unit': '%' if kind == 'relative' else 'п.п.',
                'limit': limit,
                'ci_share_pct': share,
                'within': within,
                'passed_by': passed_by,
            }
        channels.append({
            'channel': name,
            'quantities': quantities,
            'verdict': 'match' if channel_within else 'mismatch',
        })
        all_within = all_within and channel_within

    return {
        'status': 'compared',
        'verdict': 'match' if all_within else 'mismatch',
        'mode': used_mode,
        'mode_title': MODE_TITLES[used_mode],
        'mode_reason': reason,
        'criterion_version': CRITERION_VERSION,
        'tolerances': dict(limits),
        'ci_share_limit_pct': CI_SHARE_LIMIT_PCT,
        'channels': channels,
        'unverified': unverified,
        'notes': notes,
    }


# ── Клиентская формулировка критерия ─────────────────────────────────────────

def criterion_for_certificate(passport: dict[str, Any] | None = None) -> dict[str, Any]:
    """Критерий совпадения в виде, пригодном для сертификата методологии.

    Числа берутся из тех же констант, что применяет сверка: документ и проверка
    не вправе разойтись.

    Args:
        passport: паспорт прогона этой модели. Если передан, критерий
            дополнительно объявляет ветвь, применимую К ЭТОМУ расчёту, – она
            считается из числа итоговых выборок паспорта, а не выбирается
            читателем. Без паспорта раздел `applicable` остаётся пустым: назвать
            ветвь наугад значило бы обмануть.
    """
    применимая: dict[str, Any] | None = None
    if passport:
        режим, причина = applicable_mode(passport)
        применимая = {
            'mode': режим,
            'title': MODE_TITLES[режим],
            'tolerances': dict(TOLERANCES[режим]),
            'reason': причина,
            'total_draws': total_draws(passport),
        }

    return {
        'version': CRITERION_VERSION,
        'quantities': [title for title, _ in QUANTITIES.values()],
        'quantities_from_decomposition': {
            'quantities': [QUANTITIES[key][0] for key in QUANTITIES_FROM_DECOMPOSITION],
            'where_to_find': DECOMPOSITION_QUANTITIES_SOURCE,
            'note': DECOMPOSITION_UNVERIFIED_NOTE,
        },
        'full_run_draws': FULL_RUN_DRAWS,
        'applicable': применимая,
        'exact': {
            'title': MODE_TITLES[MODE_EXACT],
            'tolerance': 'совпадение точное',
            'note': SELF_RERUN_NOTE,
        },
        'other_seed_full': {
            'title': MODE_TITLES[MODE_STRICT],
            'tolerances': dict(TOLERANCES[MODE_STRICT]),
        },
        'reduced_or_other_env': {
            'title': MODE_TITLES[MODE_WIDE],
            'tolerances': dict(TOLERANCES[MODE_WIDE]),
        },
        'ci_share_limit_pct': CI_SHARE_LIMIT_PCT,
    }


def criterion_lines(criterion: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Строки «название – значение» для сертификата в отчёте и в презентации.

    Args:
        criterion: результат `criterion_for_certificate` для этой модели. Если
            в нём объявлена применимая ветвь, она печатается отдельной строкой –
            читателю не приходится выбирать ветвь самому и ошибаться в пользу
            строгой (замечание С-2). Без него строки описывают критерий вообще.
    """
    строгий = TOLERANCES[MODE_STRICT]
    широкий = TOLERANCES[MODE_WIDE]
    строки = [
        ('Что сверяется', 'окупаемость и вклад каналов, коэффициенты каналов, '
                          'перенос и насыщение'),
        ('Где взять окупаемость и долю вклада',
         f'{DECOMPOSITION_QUANTITIES_SOURCE}. {DECOMPOSITION_UNVERIFIED_NOTE}'),
    ]

    применимая = (criterion or {}).get('applicable') if isinstance(criterion, dict) else None
    if isinstance(применимая, dict) and применимая.get('mode') in TOLERANCES:
        допуски = применимая.get('tolerances') or TOLERANCES[применимая['mode']]
        строки.append((
            'Ветвь, применимая к этому расчёту',
            f'{применимая.get("title")}. {применимая.get("reason", "")} '
            f'Допуск: окупаемость, коэффициент, перенос и насыщение – в пределах '
            f'{_число(допуски["roi"])} %, доля канала во вкладе – в пределах '
            f'{_пункты(допуски["contribution_pct"])}'.strip(),
        ))

    строки += [
        ('Повторный запуск той же программой',
         f'числа обязаны совпасть точно. {SELF_RERUN_NOTE}'),
        ('Другое зерно, полный расчёт',
         f'окупаемость, коэффициент, перенос и насыщение – в пределах '
         f'{_число(строгий["roi"])} %, доля канала во вкладе – в пределах '
         f'{_пункты(строгий["contribution_pct"])}; полным считается расчёт от '
         f'{FULL_RUN_DRAWS} итоговых выборок'),
        ('Сокращённый расчёт или другая среда',
         f'те же величины – в пределах {_число(широкий["roi"])} %, доля канала – '
         f'в пределах {_пункты(широкий["contribution_pct"])}'),
        ('Дополнительно',
         f'расхождение засчитывается как совпадение и тогда, когда оно не '
         f'превышает {_число(CI_SHARE_LIMIT_PCT)} % ширины правдоподобного '
         f'диапазона той же величины'),
    ]
    return строки


def criterion_note() -> str:
    """Пояснение к критерию – одним абзацем, для клиента."""
    return (
        'Оценка модели опирается на случайную процедуру, поэтому повтор расчёта '
        'с другим зерном даёт близкие, но не тождественные числа. Критерий '
        'говорит, какое расхождение считается совпадением: при повторном запуске '
        'программой самой себя числа обязаны совпасть точно, при проверке другой '
        'программой либо другим зерном допускается расхождение в объявленных '
        'пределах. Какая из ветвей применима к этому расчёту, определяет сам '
        'паспорт – по числу итоговых выборок прогона. Пределы получены '
        'измерением повторных прогонов, а не назначены.'
    )


def _число(значение: float) -> str:
    """Число для клиентского текста: без хвостового нуля, с запятой."""
    текст = f'{значение:.1f}'.rstrip('0').rstrip('.')
    return текст.replace('.', ',')


def _пункты(значение: float) -> str:
    """Процентные пункты словами, с согласованием после предлога «в пределах»."""
    форма = 'процентного пункта' if значение < 2 else 'процентных пунктов'
    return f'{_число(значение)} {форма}'


# ── Границы критерия ─────────────────────────────────────────────────────────
#
# Критерий НЕ покрывает:
#
# * расхождение между разными МАШИНАМИ и сборками библиотек – оно не измерено;
#   такие пары попадают в самый широкий допуск, но выдержит ли его иная машина,
#   мы не проверяли;
# * каналы, отсутствующие в одном из расчётов, и расчёты по разным данным – это
#   не «несовпадение в пределах допуска», а несравнимые расчёты, и сверка
#   отказывает явно;
# * величины, которых нет в разбивке (окупаемость и вклад при недоступных
#   исходных данных) – они объявляются несверявшимися, а не совпавшими; сверка
#   ТОЛЬКО по паспорту к ним не подступается вовсе: их там нет по построению,
#   и критерий говорит об этом прямо, а адрес их публикации называет;
# * сторонняя проверка ветвью «повторный запуск той же программой»: побитовое
#   совпадение даёт идентичность кода, а не зерно и среда, поэтому посторонний
#   к этой ветви не допускается – ему адресованы ветви 2 и 3;
# * согласованность выводов: два расчёта могут совпасть по всем числам и всё же
#   привести к разным советам, если совет строится на порядке каналов, а два
#   канала стоят вплотную;
# * данные тоньше или каналы мельче наших: допуски измерены на проекте с 31
#   наблюдением и четырьмя каналами, доля самого малого из них во вкладе –
#   около 12 %. Канал с долей в считанные проценты имеет более широкий разброс,
#   и его защищает вторая опора критерия (доля правдоподобного диапазона), а не
#   проценты;
# * качество модели: критерий отвечает на вопрос «повторяется ли расчёт», а не
#   «верен ли он».
